# Pinterest board downloader

Pindl is a simple Python 3 program to download images from Pinterest
boards.


## Access token

Pindl uses the official [Pinterest API][API], so you'll need to obtain
an access token at https://developers.pinterest.com/tools/access_token/.
`read_public` will be enough to use pindl.

Pindl will search for your token in the following places
(in order of priority):

* `-a, --access-token` argument
* `pin_token` file in the current working directory
* `pin_token` file in the same directory as `pindl.py`
* `.pin_token` file in your home directory


## Names and paths

Each board will be saved in `{user_name}/{board_name}` subdirectory.
The base output directory can be set via `-o, --out-dir` option,
which is the current working directory by default.

Each image will have a name in `{pin_description}_{pin_id}.{extension}`
format (or just `{pin_id}.{extension}` if the description is empty).

Pindl will check for existing images by the `{pin_id}` part. If a pin
is already saved, the program will just update the `{pin_description}`.

For convenience, pindl applies the following conversions to each file name:

* The whole file name is converted to lowercase.
* All spaces (including multiple occurrences) replaced by an underscore.
* `{pin_description}` is limited to 50 characters.


## Rate limiting and pagination

The Pinterset API splits bard into pages, up to 100 pins per page. The
number of API calls per hour is limited to 1000. These means that you
can download up to 100 000 images per hour. The actual number depends
on how many board you download and how many pins each one contains:
the program makes an additional API call for each board to retrieve its
information (the total number of pins, author's name, etc.), and an
extra call for "all" to get a list of your public boards. Enabling
`-d, --debug` option will allow you to see the current rate limit.

To keep track of downloaded pages, pindl saves the cursor to the next
page and the number of downloaded pages in a
`{user_name}/{board_name}.json` file. If the downloading will be
interrupted (manually or due to errors, like exceeding the rate limit),
the program will automatically load the cursor from this file and
continue downloading from the last page.

You can set the page cursor by manually editing the file. Too see
cursors and page numbers, you will need to enable debugging output
via `-d, --debug` option. Since a cursor refers to the *next* page
to download, there is no cursor for the first page.

For more information, visit [the API documentation][API]:

* [Rate limiting](https://developers.pinterest.com/docs/api/overview/#rate-limiting)
* [Pagination](https://developers.pinterest.com/docs/api/overview/#pagination)


## Usage notes

* As of 12.2015, the Pinterest API does not provide access to secret
  boards, so you need to make them temporarily public to download.

* On Windows, don't forget to set UTF-8 in your command prompt if your
  Python is older than 3.6.0:

        chcp 65001

    Or use PYTHONIOENCODING environment variable instead:

        set PYTHONIOENCODING=UTF-8


[API]: https://developers.pinterest.com/docs/api/overview/ "Pinterest API"
