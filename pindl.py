#!/usr/bin/env python3

# Pinterest board downloader
#
# Copyright (c) 2015, 2016 Daniel Plachotich
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

from http import cookiejar
import urllib.request
import urllib.parse
from urllib.error import URLError
import zlib
import json


API = 'https://api.pinterest.com/v1/'

# File containing an access token.
_TOKEN_FILE = 'pin_token'

# Maximum length of the pin note (description).
_NOTE_LIMIT = 50


_FILENAME_TRANS = str.maketrans('\\/"', '--\'', '<>:|?*')


def universal_filename(s):
    '''Create a file name compatible with MS file systems.'''
    return s.translate(_FILENAME_TRANS).rstrip('. ')


def limit_string(s, length):
    '''Limit string to the given length.

    Ellipsis appended if needed.
    '''
    return (s[:length - 1].rstrip() + '…') if len(s) > length else s


def limit_string_bytes(s, byte_length):
    '''Limit string to the given number of bytes.'''
    return s.encode()[:byte_length].decode(errors='ignore')


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
    '''Read data from the response.

    The function will take care of compression, if any.
    '''
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


def get_text(url):
    request = urllib.request.Request(
        url, headers={'Accept-Encoding': 'gzip, deflate'})

    with urllib.request.urlopen(request) as response:
        return read_response(response).decode()


def create_pin_filename(pin, image_ext=''):
    '''Create a file name for the pin image.

    pin -- a pin info from the API response. "id" and "note" fields
        are required.
    image_ext -- custom image extension (with a leading period).
    '''
    if not pin['note']:
        return pin['id'] + image_ext

    # Limit the note length.
    # The maximum length of a path component is 255 bytes (minus 1 byte
    # of the underscore). Assume that both id and extension are ASCII-only.
    note = limit_string_bytes(
        pin['note'], 254 - len(pin['id']) - len(image_ext))
    note = limit_string(note, _NOTE_LIMIT)

    note = universal_filename(note)
    note = '_'.join(note.lower().split())
    if note:
        note += '_'

    return '{}{}{}'.format(note, pin['id'], image_ext)


def get_existing_pins(path):
    '''Get a list of pins in the path.

    Returns a dict {pin_id: file_name}.
    '''
    pins = {}

    for file_name in next(os.walk(path))[2]:
        name = os.path.splitext(file_name)[0]
        pin_id = name[name.rfind('_') + 1:]
        if pin_id.isalnum():
            pins[pin_id] = file_name

    return pins


def iter_pins(board, access_token):
    '''Iterate over all pins on the board.

    board -- a board id or user_name/board_name combination.
    '''
    query = urllib.parse.urlencode({
        'access_token': access_token,
        'fields': 'id,note,image',
        'limit': '100',
        })
    url = '{}boards/{}/pins/?{}'.format(API, urllib.parse.quote(board), query)

    while True:
        board = json.loads(get_text(url))

        for pin in board['data']:
            yield pin

        url = board['page']['next']
        if url is None:
            break


def download_board(board, access_token):
    '''Download all pins from the board.

    board -- a board id or user_name/board_name combination.
    '''
    query = urllib.parse.urlencode({
        'access_token': access_token,
        'fields': 'id,name,url,creator,counts'
        })
    url = '{}boards/{}/?{}'.format(API, urllib.parse.quote(board), query)

    board_info = json.loads(get_text(url))['data']

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
    path = board.replace('/', os.sep)
    os.makedirs(path, exist_ok=True)

    existing_pins = get_existing_pins(path)

    for pin_num, pin in enumerate(iter_pins(board, access_token), 1):
        if pin['id'] in existing_pins:
            old_file_name = existing_pins[pin['id']]
            new_file_name = create_pin_filename(
                pin, os.path.splitext(old_file_name)[1])

            if new_file_name == old_file_name:
                logging.info(
                    'Pin %s already exists as:\n  %s',
                    pin['id'], old_file_name)
                continue

            os.rename(
                os.path.join(path, old_file_name),
                os.path.join(path, new_file_name))
            logging.info(
                'Pin %s file name updated:\n  Old: %s\n  New: %s',
                pin['id'], old_file_name, new_file_name)
            continue

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
        print('{}/{} {}'.format(pin_num, num_pins, image_name))

        with open(image_path, 'wb') as f:
            f.write(image_data)


def download_all_my_boards(access_token):
    '''Download all boards of the authenticated user.'''
    query = urllib.parse.urlencode({
        'access_token': access_token,
        'fields': 'id,url'
        })
    url = '{}me/boards/?{}'.format(API, query)

    boards = json.loads(get_text(url))['data']
    if not boards:
        print('You have no public boards')
        return

    for board in boards:
        download_board(
            urllib.parse.unquote(
                urllib.parse.urlsplit(board['url']).path.strip('/')),
            access_token)


def parse_args():
    parser = argparse.ArgumentParser(
        description='Pinterest board downloader',
        usage='%(prog)s [OPTIONS] BOARD [BOARD..]',
        formatter_class=argparse.RawDescriptionHelpFormatter)

    parser.add_argument(
        '-v', '--version', action='version', version='%(prog)s 1.0.0')

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
        '-d', '--debug', action='store_const',
        dest='loglevel', const=logging.DEBUG,
        help='Print debugging info.')

    args = parser.parse_args()
    if not args.batch_file and not args.boards:
        parser.error('You must provide at least one board.')

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
                download_all_my_boards(access_token)
            else:
                board = urllib.parse.unquote(
                    urllib.parse.urlsplit(board).path.strip('/'))
                download_board(board, access_token)
        except URLError as e:
            logging.error('%s: %s', board, e)


if __name__ == '__main__':
    main()
