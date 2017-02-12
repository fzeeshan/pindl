#!/usr/bin/env python3

# Pinterest board downloader
#
# Copyright (c) 2015-2017 Daniel Plakhotich
#
# This software is provided 'as-is', without any express or implied
# warranty. In no event will the authors be held liable for any damages
# arising from the use of this software.
#
# Permission is granted to anyone to use this software for any purpose,
# including commercial applications, and to alter it and redistribute it
# freely, subject to the following restrictions:
#
# 1. The origin of this software must not be misrepresented; you must not
#    claim that you wrote the original software. If you use this software
#    in a product, an acknowledgement in the product documentation would be
#    appreciated but is not required.
# 2. Altered source versions must be plainly marked as such, and must not be
#    misrepresented as being the original software.
# 3. This notice may not be removed or altered from any source distribution.

import argparse
import logging
import itertools
import os
import sys
import imghdr
import textwrap
import concurrent.futures

from http import cookiejar
import urllib.request
import urllib.parse
from urllib.error import URLError
import zlib
import json


VERSION = '1.0.1'


API = 'https://api.pinterest.com/v1/'

# File containing an access token.
_TOKEN_FILE = 'pin_token'

# Maximum length of the pin note (description) to be used in image name.
_NOTE_LIMIT = 50

_PINS_PER_PAGE = 100  # The maximum is 100


_FILENAME_TRANS = str.maketrans('\\/"', '--\'', '<>:|?*')


def universal_filename(s):
    """Create a file name compatible with MS file systems."""
    return s.translate(_FILENAME_TRANS).rstrip('. ')


def limit_string(s, length):
    """Limit string to the given length.

    Ellipsis appended if needed.
    """
    return (s[:length - 1] + '…') if len(s) > length else s


_ELLIPSIS_BYTE_LEN = len('…'.encode())


def limit_string_bytes(s, byte_length):
    """Limit string to the given number of bytes.

    Ellipsis appended if needed.
    """
    encoded = s.encode()
    if len(encoded) <= byte_length:
        return s
    elif byte_length < _ELLIPSIS_BYTE_LEN:
        return ''
    elif byte_length == _ELLIPSIS_BYTE_LEN:
        return '…'
    else:
        byte_length -= _ELLIPSIS_BYTE_LEN
        return encoded[:byte_length].decode(errors='ignore') + '…'


def setup_opener():
    opener = urllib.request.build_opener(
        urllib.request.HTTPCookieProcessor(
            cookiejar.CookieJar()))

    opener.addheaders = [
        ('User-Agent', (
            'Mozilla/5.0 (X11; Ubuntu; Linux x86_64; rv:41.0) '
            'Gecko/20100101 Firefox/41.0')),
        ('Accept', '*/*'),
        ('Accept-Language', 'en'),
        ]

    urllib.request.install_opener(opener)


def read_response(response):
    """Read data from the response.

    The function will take care of compression, if any.
    """
    data = response.read()

    encoding = response.getheader('Content-Encoding')
    if encoding not in ('gzip', 'deflate'):
        return data

    # http://www.zlib.net/zlib_faq.html#faq39
    decompressed_data = zlib.decompress(data, zlib.MAX_WBITS + 32)
    logging.debug(
        '%s data decompressed: %d -> %d',
        encoding,
        len(data),
        len(decompressed_data))
    return decompressed_data


def api_call(url):
    request = urllib.request.Request(
        url, headers={'Accept-Encoding': 'gzip, deflate'})

    with urllib.request.urlopen(request) as response:
        logging.debug(
            'Rate limit: %s/%s',
            response.getheader('X-Ratelimit-Remaining'),
            response.getheader('X-Ratelimit-Limit'))
        return json.loads(read_response(response).decode())


def create_pin_filename(pin, image_ext):
    """Create a file name for the pin image.

    pin -- a pin info from the API response. "id" and "note" fields
        are required.
    image_ext -- image extension with a leading period.
    """
    note = pin['note'].lstrip('.')
    if not note:
        return pin['id'] + image_ext

    note = limit_string(note, _NOTE_LIMIT)
    # The maximum length of a path component is 255 bytes (minus 1 byte
    # of the underscore). Assume that both id and extension are ASCII-only.
    note = limit_string_bytes(
        note, 254 - len(pin['id']) - len(image_ext))

    note = universal_filename(note)
    note = '_'.join(note.lower().split())
    if note:
        note += '_'

    return note + pin['id'] + image_ext


def get_existing_pins(path):
    """Get a list of pins in the path.

    Returns a dict {pin_id: file_name}.
    """
    pins = {}

    for file_name in next(os.walk(path))[2]:
        name = os.path.splitext(file_name)[0]
        pin_id = name[name.rfind('_') + 1:]
        if pin_id.isalnum():
            pins[pin_id] = file_name

    return pins


def iter_board_pages(board, access_token, page_cursor=None):
    """Iterate over pages of a board.

    board -- a board id or user_name/board_name combination.
    page_cursor -- the cursor to the next page to download, or None to
        start from the first page.

    Yields a list of pins on the current page and the cursor to
    the next page (will be None for the last page).
    """
    query = {
        'access_token': access_token,
        'fields': 'id,note,image',
        'limit': _PINS_PER_PAGE,
        }
    if page_cursor:
        query['cursor'] = page_cursor

    url = '{}boards/{}/pins/?{}'.format(
        API, urllib.parse.quote(board), urllib.parse.urlencode(query))

    while True:
        board = api_call(url)

        yield board['data'], board['page']['cursor']

        url = board['page']['next']
        if url is None:
            break


def download_pin(pin, path):
    image_url = pin['image']['original']['url']
    with urllib.request.urlopen(image_url) as response:
        image_data = response.read()

    image_ext = os.path.splitext(image_url)[1]

    # Sometimes non-JPEG images have .jpg extension.
    if image_ext == '.jpg':
        image_type = imghdr.what(None, image_data)
        if image_type not in (None, 'jpeg'):
            image_ext = '.' + image_type
            logging.debug(
                '%s image extension corrected', image_type.upper())

    image_name = create_pin_filename(pin, image_ext)
    image_path = os.path.join(path, image_name)

    with open(image_path, 'wb') as f:
        f.write(image_data)


def create_progress_printer(num_pins):
    """Create a progress printer.

    num_pins -- the total number of pins.

    Returns a callable that takes a pin and its current number.
    """
    total_width = 79

    num_width = len(str(num_pins))
    num_field_width = num_width * 2 + 1  # Plus the length of the slash
    num_spaces = 2
    free_width = max(0, total_width - num_field_width - num_spaces)

    template = '{{:{}}}/{} {}'.format(num_width, num_pins, '{:{}} {:{}}')

    def printer(pin, pin_num):
        id_len = len(pin['id'])
        note_len = max(0, free_width - id_len)
        note = limit_string(pin['note'], note_len)
        print(template.format(pin_num, note, note_len, pin['id'], id_len))

    return printer


def download_board(board, access_token, out_dir, num_threads):
    """Download all pins from the board.

    board -- a board id or user_name/board_name combination.
    """
    query = {
        'access_token': access_token,
        'fields': 'id,name,url,creator,counts'
        }
    url = '{}boards/{}/?{}'.format(
        API, urllib.parse.quote(board), urllib.parse.urlencode(query))

    board_info = api_call(url)['data']

    num_pins = board_info['counts']['pins']
    creator = board_info['creator']

    print('\n{}\nby {}\n{} pins\n'.format(
        board_info['name'],
        ' '.join((creator['first_name'], creator['last_name'])),
        num_pins
        ))

    if board == board_info['id']:
        board = urllib.parse.unquote(
            urllib.parse.urlsplit(board_info['url']).path.strip('/'))
    path = os.path.join(out_dir, board.replace('/', os.sep))
    os.makedirs(path, exist_ok=True)

    page_info_path = path + '.json'
    try:
        with open(page_info_path, 'r', encoding='utf-8') as f:
            page_info = json.load(f)
    except FileNotFoundError:
        page_info = {}

    page_num = page_info.get('num_complete_pages', 0)
    pin_num = page_num * _PINS_PER_PAGE

    existing_pins = get_existing_pins(path)
    print_progress = create_progress_printer(num_pins)

    for pins, cursor in iter_board_pages(
            board, access_token, page_info.get('next_page_cursor')):
        page_num += 1
        logging.debug('Page: %s', page_num)
        logging.debug('Next page cursor: %s', cursor)

        new_pins = []
        for pin in pins:
            if pin['id'] not in existing_pins:
                new_pins.append(pin)
            else:
                old_file_name = existing_pins[pin['id']]
                new_file_name = create_pin_filename(
                    pin, os.path.splitext(old_file_name)[1])

                if new_file_name == old_file_name:
                    logging.info(
                        'Pin %s already exists as:\n  %s',
                        pin['id'], old_file_name)
                else:
                    os.rename(
                        os.path.join(path, old_file_name),
                        os.path.join(path, new_file_name))
                    logging.info(
                        'Pin %s file name updated:\n  Old: %s\n  New: %s',
                        pin['id'], old_file_name, new_file_name)

        pin_num += len(pins) - len(new_pins)
        logging.debug('%s new pins on this page', len(new_pins))

        if new_pins:
            num_errors = 0
            with concurrent.futures.ThreadPoolExecutor(
                    num_threads) as executor:
                future_to_pin = {}
                for pin in new_pins:
                    future = executor.submit(download_pin, pin, path)
                    future_to_pin[future] = pin

                for future in concurrent.futures.as_completed(future_to_pin):
                    # Print the exception before the progress message so that
                    # it will appear together with debugging messages.
                    e = future.exception()
                    if e is not None:
                        logging.error(e)
                        num_errors += 1

                    pin_num += 1
                    pin = future_to_pin[future]
                    print_progress(pin, pin_num)

            if num_errors > 0:
                logging.error(
                    'The page was not downloaded completely: '
                    '%s pins left to download. Please try again later.',
                    num_errors)
                return

        if cursor is not None:
            page_info = {
                'next_page_cursor': cursor,
                'num_complete_pages': page_num
            }
            with open(page_info_path, 'w', encoding='utf-8') as f:
                json.dump(page_info, f, ensure_ascii=False, indent=2)
        else:
            # This is the last page
            try:
                os.remove(page_info_path)
            except FileNotFoundError:
                pass


def download_all_my_boards(access_token, out_dir, num_threads):
    """Download all boards of the authenticated user."""
    query = {
        'access_token': access_token,
        'fields': 'id,url'
        }
    url = '{}me/boards/?{}'.format(API, urllib.parse.urlencode(query))

    boards = api_call(url)['data']
    if not boards:
        print('You have no public boards')
        return

    for board in boards:
        download_board(
            urllib.parse.unquote(
                urllib.parse.urlsplit(board['url']).path.strip('/')),
            access_token,
            out_dir,
            num_threads)


def parse_args():
    parser = argparse.ArgumentParser(
        description='Pinterest board downloader',
        usage='%(prog)s [OPTIONS] BOARD [BOARD..]',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=textwrap.dedent("""
            Before using pindl, visit
            https://developers.pinterest.com/tools/access_token/
            to generate an access token. "read_public" will be enough.

            Pindl will search for your access token in the following places
            (in order of priority):
              * -a, --access-token argument
              * pin_token file in the current working directory
              * pin_token file in the same directory as pindl.py
              * .pin_token file in your home directory

            On Windows, don\'t forget to enable UTF-8 in your command prompt
            before using pindl:
              chcp 65001
            Or set PYTHONIOENCODING environment variable instead:
              set PYTHONIOENCODING=UTF-8
            """))

    parser.add_argument(
        '-v', '--version', action='version', version='%(prog)s ' + VERSION)

    parser.add_argument(
        'boards', nargs=argparse.REMAINDER,
        help=(
            'List of boards to download. Each item can be a full board URL, '
            'user_name/board_name combination or board id. You can also use '
            '"all" to download all your public boards.'))
    parser.add_argument(
        '-b', '--batch-file', metavar='FILE',
        type=argparse.FileType('r', encoding='utf-8'),
        help='File containing boards to download (or "-" for stdin).')
    parser.add_argument(
        '-a', '--access-token', metavar='TOKEN',
        help='Access token to use instead of saved in the file.')
    parser.add_argument(
        '-o', '--out-dir', metavar='DIR', default='.',
        help=(
            'Directory to save images in. '
            'Default is the current working directory.'))
    parser.add_argument(
        '-t', '--threads', type=int, default=10,
        help='Number of downloading threads. Default is 10.')
    parser.add_argument(
        '-d', '--debug', action='store_const',
        dest='loglevel', const=logging.DEBUG,
        help='Print debugging info.')

    args = parser.parse_args()
    if not args.batch_file and not args.boards:
        parser.error('You must provide at least one board.')

    if args.threads < 1:
        parser.error('The number of threads should be >= 1')

    return args


def main():
    args = parse_args()

    logging.basicConfig(
        level=args.loglevel,
        format='%(levelname)s: %(message)s')

    if args.access_token:
        access_token = args.access_token
    else:
        access_token = ''
        for file_name in (
                _TOKEN_FILE,
                os.path.join(
                    os.path.dirname(os.path.realpath(__file__)), _TOKEN_FILE),
                os.path.join(
                    os.path.expanduser('~'), '.' + _TOKEN_FILE)):
            try:
                with open(file_name, 'r') as f:
                    for line in (l.strip() for l in f):
                        if line:
                            access_token = line
                            logging.debug(
                                'Access token is loaded from %s', file_name)
                            break
            except FileNotFoundError:
                pass
            else:
                if access_token:
                    break
        else:
            sys.exit(
                'You need to obtain an access token from Pinterest:\n'
                'https://developers.pinterest.com/tools/access_token/')

    setup_opener()

    if args.batch_file:
        boards = itertools.chain(
            args.boards,
            filter(None, (l.strip() for l in args.batch_file)))
    else:
        boards = args.boards

    for board in boards:
        try:
            if board == 'all':
                download_all_my_boards(
                    access_token, args.out_dir, args.threads)
            else:
                board = urllib.parse.unquote(
                    urllib.parse.urlsplit(board).path.strip('/'))
                download_board(board, access_token, args.out_dir, args.threads)
        except URLError as e:
            logging.error('%s: %s', board, e)


if __name__ == '__main__':
    main()
