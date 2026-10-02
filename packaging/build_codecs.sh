#!/bin/bash
set -euo pipefail
ROOT=$(cd "$(dirname "$0")/.." && pwd)
ARCH=${DISC_PORTER_ARCH:-arm64}
WORK="$ROOT/packaging/cache/codec-build-$ARCH"
PREFIX="$ROOT/packaging/cache/codecs-$ARCH-macos14"
OUT=${DISC_PORTER_TOOLS_OUTPUT:-"$ROOT/packaging/dist/Tools"}
if [[ "$ARCH" == "x86_64" ]]; then HOST=x86_64; ASMFLAGS=--disable-asm; FFMPEGASM=--disable-x86asm; X265_ASM=OFF; else HOST=aarch64; ASMFLAGS=; FFMPEGASM=; X265_ASM=ON; fi
mkdir -p "$WORK" "$PREFIX" "$OUT"
python3 "$ROOT/packaging/fetch_sources.py"
export MACOSX_DEPLOYMENT_TARGET=14.0
export CC=clang CXX=clang++
export CFLAGS="-O2 -arch $ARCH -mmacosx-version-min=14.0"
export CXXFLAGS="$CFLAGS"
export LDFLAGS="-arch $ARCH -mmacosx-version-min=14.0"
export PKG_CONFIG="$PREFIX/bin/pkgconf"
export PKG_CONFIG_PATH="$PREFIX/lib/pkgconfig"
JOBS=${DISC_PORTER_BUILD_JOBS:-8}
if [[ ! -d "$WORK/x264" ]]; then mkdir "$WORK/x264"; tar -xf "$ROOT/packaging/sources/x264-r3222.tar.gz" -C "$WORK/x264" --strip-components=1; fi
if [[ ! -f "$WORK/x265/source/CMakeLists.txt" ]]; then mkdir -p "$WORK/x265"; tar -xf "$ROOT/packaging/sources/x265-4.2.2.tar.gz" -C "$WORK/x265" --strip-components=1; fi
if [[ ! -d "$WORK/ffmpeg" ]]; then mkdir "$WORK/ffmpeg"; tar -xf "$ROOT/packaging/sources/ffmpeg-9.0.1.0.1.tar.xz" -C "$WORK/ffmpeg" --strip-components=1; fi
if [[ ! -x "$PREFIX/bin/pkgconf" ]]; then
 cp "$ROOT/packaging/sources/pkgconf-2.5.1.tar.xz" "$WORK/pkgconf.tar.xz"
 mkdir -p "$WORK/pkgconf"; tar -xf "$WORK/pkgconf.tar.xz" -C "$WORK/pkgconf" --strip-components=1
 (cd "$WORK/pkgconf"; ./configure --prefix="$PREFIX" --disable-shared; make -j"$JOBS"; make install)
fi
if [[ ! -f "$PREFIX/lib/libx264.a" ]]; then
 (cd "$WORK/x264"; ./configure --prefix="$PREFIX" --enable-static --disable-cli --disable-opencl --host=$HOST-apple-darwin $ASMFLAGS --extra-cflags="$CFLAGS" --extra-ldflags="$LDFLAGS"; make -j"$JOBS"; make install)
fi
if [[ ! -f "$PREFIX/lib/libx265.a" ]]; then
 cmake -S "$WORK/x265/source" -B "$WORK/x265/10bit" -DCMAKE_INSTALL_PREFIX="$PREFIX" -DCMAKE_OSX_DEPLOYMENT_TARGET=14.0 -DCMAKE_OSX_ARCHITECTURES=$ARCH -DENABLE_ASSEMBLY=$X265_ASM -DCMAKE_BUILD_TYPE=Release -DHIGH_BIT_DEPTH=ON -DEXPORT_C_API=OFF -DENABLE_SHARED=OFF -DENABLE_CLI=OFF
 cmake --build "$WORK/x265/10bit" -j"$JOBS"
 mkdir -p "$WORK/x265/8bit"
 cp "$WORK/x265/10bit/libx265.a" "$WORK/x265/8bit/libx265_main10.a"
 cmake -S "$WORK/x265/source" -B "$WORK/x265/8bit" -DCMAKE_INSTALL_PREFIX="$PREFIX" -DCMAKE_OSX_DEPLOYMENT_TARGET=14.0 -DCMAKE_OSX_ARCHITECTURES=$ARCH -DENABLE_ASSEMBLY=$X265_ASM -DCMAKE_BUILD_TYPE=Release -DHIGH_BIT_DEPTH=OFF -DLINKED_10BIT=ON -DEXTRA_LINK_FLAGS=-L. -DEXTRA_LIB=x265_main10.a -DENABLE_SHARED=OFF -DENABLE_CLI=OFF
 cmake --build "$WORK/x265/8bit" -j"$JOBS"
 cmake --install "$WORK/x265/8bit"
fi
if [[ ! -f "$PREFIX/lib/.multibit_complete" ]]; then
 libtool -static -o "$PREFIX/lib/libx265-combined.a" "$PREFIX/lib/libx265.a" "$WORK/x265/10bit/libx265.a"
 mv "$PREFIX/lib/libx265-combined.a" "$PREFIX/lib/libx265.a"
 touch "$PREFIX/lib/.multibit_complete"
fi
DISC_PORTER_ARCH="$ARCH" "$ROOT/packaging/build_subtitles.sh"
(cd "$WORK/ffmpeg";
 ./configure --prefix="$PREFIX" --arch=$HOST $FFMPEGASM --target-os=darwin --cc=clang --cxx=clang++ --enable-static --disable-shared --disable-autodetect --disable-network --disable-ffplay --disable-doc --enable-gpl --enable-version3 --enable-libx264 --enable-libx265 --enable-libass --enable-videotoolbox --enable-audiotoolbox --enable-pthreads --enable-zlib --enable-bzlib --pkg-config="$PKG_CONFIG" --pkg-config-flags=--static --extra-cflags="$CFLAGS -I$PREFIX/include" --extra-ldflags="$LDFLAGS -L$PREFIX/lib" --extra-libs=-lc++;
 python3 "$ROOT/packaging/sanitize_build_metadata.py" "$WORK/ffmpeg" "$ROOT"
 make -j"$JOBS"; make install)
cp "$PREFIX/bin/ffmpeg" "$OUT/ffmpeg"
cp "$PREFIX/bin/ffprobe" "$OUT/ffprobe"
codesign --force --sign - "$OUT/ffmpeg" "$OUT/ffprobe"
"$ROOT/packaging/.venv/bin/python" "$ROOT/packaging/bundle_tools.py" --ffmpeg "$PREFIX/bin/ffmpeg" --ffprobe "$PREFIX/bin/ffprobe" --output "$OUT" --architecture "$ARCH"
# Configure records are exact compiler inputs; archive files remain outside user artifacts.
mkdir -p "$ROOT/packaging/provenance/source-built-codecs-$ARCH"
cp "$WORK/ffmpeg/ffbuild/config.log" "$ROOT/packaging/provenance/source-built-codecs-$ARCH/ffmpeg-config.log"
cp "$WORK/ffmpeg/config.h" "$ROOT/packaging/provenance/source-built-codecs-$ARCH/ffmpeg-config.h"
cp "$WORK/x264/config.log" "$ROOT/packaging/provenance/source-built-codecs-$ARCH/x264-config.log"
cp "$WORK/x265/10bit/CMakeCache.txt" "$ROOT/packaging/provenance/source-built-codecs-$ARCH/x265-10bit-CMakeCache.txt"
cp "$WORK/x265/8bit/CMakeCache.txt" "$ROOT/packaging/provenance/source-built-codecs-$ARCH/x265-8bit-CMakeCache.txt"

python3 - "$ROOT/packaging/provenance/source-built-codecs-$ARCH" "$ROOT" <<'PYDOC'
from pathlib import Path
import sys
for p in Path(sys.argv[1]).iterdir():
 if p.is_file(): p.write_text(p.read_text().replace(sys.argv[2],'${DISC_PORTER_SOURCE_ROOT}'))
PYDOC
