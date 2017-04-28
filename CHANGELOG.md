
## 1.1.1 (2017-04-28)

* Added a workaround for wrong image URLs resulting in 403 HTTP
  error (#2)
* Pindl no longer terminates the board downloading on HTTP errors (#2)
* HTTP errors are now printed after progress messages


## 1.1.0 (2017-02-12)

* Added `-o, --out-dir` option to set the output directory
* Added support for multithreaded downloading. The number of threads
  can be controlled via `-t, --threads` option.
* Leading periods are now stripped from image names
