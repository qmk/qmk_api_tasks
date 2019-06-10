# QMK API Tasks

Long-running service that continually exercises the QMK Compile Infrastructure.

## Goals

* Always have a compile job running
* Iterate through all keyboards looking for problems

## Style

We follow the style guidelines for QMK and have provided a yapf config in setup.cfg.

## See Also

The main entrypoint to hacking on this api is [qmk/qmk_api](https://github.com/qmk/qmk_api). Our documentation lives on GitBook and can be found here:

> https://docs.compile.qmk.fm
