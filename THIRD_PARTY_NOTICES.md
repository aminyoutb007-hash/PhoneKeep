# Third-party notices

PhoneKeep is free software under the GNU General Public License, version 3 or (at your option) any later version
(GPL-3.0-or-later): see LICENSE. The Mac app and the Windows installer also contain the libraries below, each under
its own licence. All of them can be combined with and passed on under GPL-3.0-or-later.

The full licence text of each Python library is shipped inside the app, in that library's `.dist-info` folder (Mac:
`PhoneKeep.app/Contents/Resources/`; Windows: the `_internal` folder next to `PhoneKeep.exe`). The source of every
library is at the address given.

Licences were checked from each package's own metadata and licence file (Mac build, 14 Nov 2026). An installer may
carry a newer release of the same library; `tests/test_licence.py` fails when the app depends on a library that isn't
listed here.

## Python libraries

| Library | Licence |
|---|---|
| [aiofiles](https://github.com/Tinche/aiofiles) | Apache-2.0 |
| [altgraph](https://altgraph.readthedocs.io) | MIT |
| [annotated-doc](https://github.com/fastapi/annotated-doc) | MIT |
| [annotated-types](https://github.com/annotated-types/annotated-types) | MIT |
| [ansilogs](https://github.com/doronz88/ansilogs) | MIT |
| [anyio](https://github.com/agronholm/anyio) | MIT |
| [apple-compress](https://github.com/m1stadev/apple-compress) | MIT ¹ |
| [arabic-reshaper](https://github.com/mpcabd/python-arabic-reshaper/) | MIT |
| [arrow](https://github.com/arrow-py/arrow) | Apache-2.0 |
| [ASGIMiddlewareStaticFile](https://github.com/rexzhang/asgi-middleware-static-file) | MIT ¹ |
| [asgiref](https://github.com/django/asgiref/) | BSD-3-Clause |
| [ASGIWebDAV](https://github.com/rexzhang/asgi-webdav) | MIT ¹ |
| [asn1](https://github.com/andrivet/python-asn1) | MIT ² |
| [backports.zstd](https://github.com/rogdham/backports.zstd) | PSF-2.0 |
| [bpylist2](https://github.com/parabolala/bpylist2) | MIT |
| [bytestruct](https://github.com/doronz88/bytestruct) | MIT |
| [certifi](https://github.com/certifi/python-certifi) | MPL-2.0 |
| [cffi](https://github.com/python-cffi/cffi) | MIT-0 |
| [chardet](https://github.com/chardet/chardet) | 0BSD |
| [charset-normalizer](https://github.com/jawah/charset_normalizer) | MIT |
| [click](https://github.com/pallets/click/) | BSD-3-Clause |
| [construct](http://construct.readthedocs.org) | MIT |
| [cryptography](https://github.com/pyca/cryptography) | Apache-2.0 OR BSD-3-Clause |
| [daemonize](https://github.com/thesharp/daemonize) | MIT |
| [dataclass-wizard](https://github.com/rnag/dataclass-wizard) | Apache-2.0 |
| [defusedxml](https://github.com/tiran/defusedxml) | PSF-2.0 |
| [developer_disk_image](https://github.com/doronz88/DeveloperDiskImage) | GPL-3.0-or-later |
| [enum-compat](https://github.com/jstasiak/enum-compat) | MIT |
| [et_xmlfile](https://foss.heptapod.net/openpyxl/et_xmlfile) | MIT |
| [fastapi](https://github.com/fastapi/fastapi) | MIT |
| [h11](https://github.com/python-hyper/h11) | MIT |
| [hyperframe](https://github.com/python-hyper/hyperframe/) | MIT |
| [idna](https://github.com/kjd/idna) | BSD-3-Clause |
| [ifaddr](https://github.com/pydron/ifaddr) | MIT |
| [ioregistry](https://github.com/doronz88/ioregistry) | GPL-3.0-or-later |
| [iphone_backup_decrypt](https://github.com/jsharkey13/iphone_backup_decrypt) | MIT ¹ |
| [ipsw-parser](https://github.com/doronz88/ipsw_parser) | GPL-3.0-or-later |
| [jaraco.classes](https://github.com/jaraco/jaraco.classes) | MIT |
| [jaraco.context](https://github.com/jaraco/jaraco.context) | MIT |
| [jaraco.functools](https://github.com/jaraco/jaraco.functools) | MIT |
| [keyring](https://github.com/jaraco/keyring) | MIT |
| [loguru](https://github.com/Delgan/loguru) | MIT |
| [macholib](http://github.com/ronaldoussoren/macholib) | MIT |
| [markdown-it-py](https://github.com/executablebooks/markdown-it-py) | MIT |
| [mdurl](https://github.com/executablebooks/mdurl) | MIT |
| [more-itertools](https://github.com/more-itertools/more-itertools) | MIT |
| [opack2](https://github.com/doronz88/opack2) | GPL-3.0-or-later |
| [openpyxl](https://openpyxl.readthedocs.io) | MIT |
| [opentelemetry-api](https://github.com/open-telemetry/opentelemetry-python/tree/main/opentelemetry-api) | Apache-2.0 |
| [packaging](https://github.com/pypa/packaging) | Apache-2.0 OR BSD-2-Clause |
| [pillow](https://python-pillow.org) | MIT-CMU ³ |
| [pillow_heif](https://github.com/bigcat88/pillow_heif) | BSD-3-Clause ³ |
| [pmd-net-addr](https://github.com/ccie18643/PyTCP) | GPL-3.0-or-later |
| [pmd-net-proto](https://github.com/ccie18643/PyTCP) | GPL-3.0-or-later |
| [pmd-pytcp](https://github.com/ccie18643/PyTCP) | GPL-3.0-or-later |
| [prompt_toolkit](https://github.com/prompt-toolkit/python-prompt-toolkit) | BSD-3-Clause |
| [psutil](https://github.com/giampaolo/psutil) | BSD-3-Clause |
| [pycparser](https://github.com/eliben/pycparser) | BSD-3-Clause |
| [pycrashreport](https://github.com/doronz88/pycrashreport) | GPL-3.0-or-later |
| [pycryptodome](https://www.pycryptodome.org) | BSD-2-Clause AND Unlicense AND MIT |
| [pydantic](https://github.com/pydantic/pydantic) | MIT |
| [pydantic_core](https://github.com/pydantic/pydantic) | MIT |
| [Pygments](https://pygments.org) | BSD-2-Clause |
| [pygnuutils](https://github.com/matan1008/pygnuutils) | GPL-3.0-or-later |
| [pyimg4](https://github.com/m1stadev/PyIMG4) | MIT |
| [pyinstaller](https://pyinstaller.org) | GPL-2.0-or-later WITH Bootloader-exception ⁴ |
| [pyiosbackup](https://github.com/matan1008/pyiosbackup) | GPL-3.0-or-later |
| [pykdebugparser](https://github.com/matan1008/pykdebugparser) | MIT |
| [pylzss](https://github.com/m1stadev/pylzss) | LGPL-3.0-only |
| [pymobiledevice3](https://github.com/doronz88/pymobiledevice3) | GPL-3.0-or-later |
| [pyobjc-core](https://github.com/ronaldoussoren/pyobjc) | MIT |
| [pyobjc-framework-Cocoa](https://github.com/ronaldoussoren/pyobjc) | MIT |
| [pyobjc-framework-LocalAuthentication](https://github.com/ronaldoussoren/pyobjc) | MIT |
| [pyobjc-framework-Quartz](https://github.com/ronaldoussoren/pyobjc) | MIT |
| [pyobjc-framework-Security](https://github.com/ronaldoussoren/pyobjc) | MIT |
| [python-bidi](https://github.com/MeirKriheli/python-bidi) | LGPL-3.0 ⁵ |
| [python-dateutil](https://github.com/dateutil/dateutil) | BSD-3-Clause |
| [python-dotenv](https://github.com/theskumar/python-dotenv) | BSD-3-Clause |
| [python-pcapng](https://github.com/rshk/python-pcapng) | Apache-2.0 |
| [pytun-pmd3](https://github.com/doronz88/pytun-pmd3) | MIT ² |
| [qh3](https://github.com/jawah/qh3) | BSD-3-Clause |
| [questionary](https://github.com/tmbo/questionary) | MIT |
| [remotezip2](https://github.com/doronz88/python-remotezip2) | MIT ² |
| [reportlab](https://www.reportlab.com/) | BSD-3-Clause |
| [requests](https://github.com/psf/requests) | Apache-2.0 |
| [rich](https://github.com/Textualize/rich) | MIT |
| [rumps](https://github.com/jaredks/rumps) | BSD-3-Clause |
| [Send2Trash](https://github.com/arsenetar/send2trash) | BSD-3-Clause |
| [setuptools](https://github.com/pypa/setuptools) | MIT |
| [shellingham](https://github.com/sarugaku/shellingham) | ISC |
| [sslpsk-pmd3](https://github.com/doronz88/sslpsk-pmd3) | Apache-2.0 |
| [starlette](https://github.com/Kludex/starlette) | BSD-3-Clause |
| [termcolor](https://github.com/termcolor/termcolor) | MIT |
| [tkinterdnd2](https://github.com/Eliav2/tkinterdnd2) | MIT |
| [traitlets](https://github.com/ipython/traitlets) | BSD-3-Clause |
| [typer-injector](https://github.com/BenjyWiener/typer-injector) | MIT |
| [typer](https://github.com/fastapi/typer) | MIT |
| [typing-inspection](https://github.com/pydantic/typing-inspection) | MIT |
| [typing_extensions](https://github.com/python/typing_extensions) | PSF-2.0 |
| [tzdata](https://github.com/python/tzdata) | Apache-2.0 |
| [urllib3](https://github.com/urllib3/urllib3) | MIT |
| [uvicorn](https://uvicorn.dev/) | BSD-3-Clause |
| [wcwidth](https://github.com/jquast/wcwidth) | MIT |
| [wsproto](https://github.com/python-hyper/wsproto/) | MIT |
| [xmltodict](https://github.com/martinblech/xmltodict) | MIT |

¹ The package metadata names no licence; the licence file shipped with it is MIT.
² The package metadata disagrees with itself (asn1: "BSD" and MIT; pytun-pmd3: GPL-3.0-or-later and MIT; remotezip2:
the GPL-3 text and MIT). The licence file shipped with it is MIT. Either way it can be passed on under GPL-3.0-or-later.
³ Pillow and pillow-heif bring native libraries of their own; see below.
⁴ PyInstaller turns PhoneKeep into an app. Only its small start-up program and run-time hooks are inside the app; its
licence's exception allows that in programs under any licence.
⁵ python-bidi is LGPL-3.0; its compiled part includes Rust crates under MIT or Apache-2.0 (listed in its
LICENSE-THIRD-PARTY.yml).

## Windows only

| Library | Licence |
|---|---|
| [pystray](https://github.com/moses-palmer/pystray) | LGPL-3.0 |
| [six](https://github.com/benjaminp/six) (used by pystray) | MIT |
| [lzfse](https://github.com/m1stadev/lzfse) (Windows and Linux; the Mac uses apple-compress) | MIT |
| [winrt-runtime](https://github.com/pywinrt/pywinrt) | MIT |
| [winrt-Windows.Foundation](https://github.com/pywinrt/pywinrt) | MIT |
| [winrt-Windows.Security.Credentials.UI](https://github.com/pywinrt/pywinrt) | MIT |
| MinGW-w64 runtime (in the Windows pillow-heif wheel) | GPL-3.0 with the GCC Runtime Library Exception; libwinpthread MIT and BSD |

On the Mac, pyobjc-framework-Security and enum-compat are installed with the libraries above but not used at run time.

## Linux only (built from source; there is no Linux installer)

| Library | Licence |
|---|---|
| [jeepney](https://gitlab.com/takluyver/jeepney) | MIT |
| [SecretStorage](https://github.com/mitya57/secretstorage) | BSD-3-Clause |
| [python-xlib](https://github.com/python-xlib/python-xlib) | LGPL-2.1-or-later |

PyAV (av), which pymobiledevice3 asks for outside the Mac, is left out of the app by the PyInstaller recipe.

## Native libraries

| Library | Comes with | Licence |
|---|---|---|
| [Python 3.12](https://www.python.org) | PhoneKeep's runtime | PSF-2.0 |
| [Tcl/Tk](https://www.tcl-lang.org) | Python (the window) | TCL (BSD-style) |
| [OpenSSL 3](https://www.openssl.org) | Python | Apache-2.0 |
| [SQLite](https://sqlite.org) | Python | Public domain |
| [libmpdec](https://www.bytereef.org/mpdecimal/) | Python | BSD-2-Clause |
| [libffi](https://github.com/libffi/libffi) | Python (Windows; the Mac uses its own) | MIT |
| [libtommath](https://github.com/libtom/libtommath) | Tcl/Tk | Unlicense |
| [libheif](https://github.com/strukturag/libheif) | pillow-heif | LGPL-3.0 |
| [libde265](https://github.com/strukturag/libde265) | pillow-heif | LGPL-3.0 |
| [x265](https://github.com/Multicorewareinc/x265) | pillow-heif | GPL-2.0-or-later |
| [AOM](https://aomedia.googlesource.com/aom/) | Pillow | BSD-2-Clause |
| [Brotli](https://github.com/google/brotli) | Pillow | MIT |
| [bzip2](https://sourceware.org/bzip2/) | Pillow | bzip2-1.0.6 |
| [dav1d](https://code.videolan.org/videolan/dav1d) | Pillow | BSD-2-Clause |
| [FreeType](https://freetype.org) | Pillow | FTL or GPL-2.0-or-later (PhoneKeep uses it under GPL-2.0-or-later) |
| [HarfBuzz](https://harfbuzz.github.io) | Pillow | MIT ("Old MIT") |
| [Little CMS](https://www.littlecms.com) | Pillow | MIT |
| [libavif](https://github.com/AOMediaCodec/libavif) | Pillow | BSD-2-Clause |
| [libjpeg-turbo](https://libjpeg-turbo.org) | Pillow | IJG, BSD-3-Clause and Zlib |
| [XZ Utils (liblzma)](https://tukaani.org/xz/) | Pillow, Python | 0BSD |
| [libpng](http://www.libpng.org) | Pillow | libpng-2.0 |
| [LibTIFF](https://libtiff.gitlab.io/libtiff/) | Pillow | libtiff |
| [libwebp](https://chromium.googlesource.com/webm/libwebp) | Pillow | BSD-3-Clause |
| [libyuv](https://chromium.googlesource.com/libyuv/libyuv) | Pillow | BSD-3-Clause |
| [OpenJPEG](https://www.openjpeg.org) | Pillow | BSD-2-Clause |
| [raqm](https://github.com/HOST-Oman/libraqm) | Pillow | MIT |
| [libXau, libxcb, libXdmcp](https://www.x.org) | Pillow | MIT |
| [zlib-ng](https://github.com/zlib-ng/zlib-ng) | Pillow | Zlib |
| [Zstandard](https://facebook.github.io/zstd/) | Pillow | BSD-3-Clause |

Pillow's and pillow-heif's own licence files, shipped in their `.dist-info` folders, have the full text of each.

## Fonts (in chats saved as PDF)

| Font | Licence |
|---|---|
| [DejaVu Sans](https://dejavu-fonts.github.io) | Bitstream Vera licence, with DejaVu's changes in the public domain (assets/fonts/LICENSE-DejaVu.txt) |
| [Noto Color Emoji](https://github.com/googlefonts/noto-emoji) | OFL-1.1 (the font) and Apache-2.0 (its tools and images) (assets/fonts/LICENSE-NotoColorEmoji.txt) |

## PhoneKeep's name and logo

"PhoneKeep" and the PhoneKeep logo are trademarks of the author. They are not licensed under the GPL. The app icons are
PhoneKeep's own drawings (tools/make_app_icons.py); no Apple or WhatsApp icon or logo is included.
