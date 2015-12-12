# Pinterest board downloader

Pindl is a simple Python 3 program to save Pinterest boards as images.


## Access token

Pindl uses official [Pinterest API]
(https://developers.pinterest.com/docs/api/overview/), so you need to obtain
your access token at https://developers.pinterest.com/tools/access_token/.
`read_public` will be enough to use pindl.

Pindl will search your token in the following places (in order of priority):

* `-a, --access-token` argument
* `./pin_token`
* `pin_token` in the same directory as `pindl.py`
* `~/.pin_token`


## Names and paths

Each board will be saved in `./{user_name}/{board_name}` directory.

Each image will have a name in `{pin_description}_{pin_id}.{extension}`
format (or just `{pin_id}.{extension}` if the description is empty).

Pindl will check for existing images by the `{pin_id}` part. If a pin
is already saved, the program will just update the `{pin_description}`.

For convenience, pindl applies the following conversions to each file name:

* The whole file name is converted to lowercase.
* All spaces (including multiple occurrences) replaced by the underscore.
* `{pin_description}` is limited to 50 characters.


## Usage notes

* As of 12.2015, the Pinterest API does not provide access to secret
  boards, so you need to make them temporarily public to download.

* On Windows, don't forget to set UTF-8 in your command prompt:

        chcp 65001

  Or use PYTHONIOENCODING environment variable instead:

        set PYTHONIOENCODING=UTF-8
