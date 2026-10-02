#!/bin/bash
set -euo pipefail
ROOT=$(cd "$(dirname "$0")/.." && pwd)
ARCH=${DISC_PORTER_ARCH:-arm64}
WORK="$ROOT/packaging/cache/subtitles-$ARCH"
PREFIX="$ROOT/packaging/cache/codecs-$ARCH-macos14"
JOBS=${DISC_PORTER_BUILD_JOBS:-8}
export MACOSX_DEPLOYMENT_TARGET=14.0 CC=clang CXX=clang++
export CFLAGS="-O2 -arch $ARCH -mmacosx-version-min=14.0"
export CXXFLAGS="$CFLAGS" LDFLAGS="-arch $ARCH -mmacosx-version-min=14.0 -L$PREFIX/lib"
export PKG_CONFIG="$PREFIX/bin/pkgconf" PKG_CONFIG_PATH="$PREFIX/lib/pkgconfig"
mkdir -p "$WORK"
python3 "$ROOT/packaging/fetch_sources.py"
for entry in freetype:2.14.3 harfbuzz:14.5.0 fribidi:1.0.17 libass:0.17.5; do
 name=${entry%%:*}; version=${entry#*:}
 if [[ ! -d "$WORK/$name" ]]; then mkdir "$WORK/$name"; tar -xf "$ROOT/packaging/sources/$name-$version.tar.xz" -C "$WORK/$name" --strip-components=1; fi
 done
if [[ ! -f "$PREFIX/lib/libfreetype.a" ]]; then
 (cd "$WORK/freetype"; ./configure --prefix="$PREFIX" --enable-static --disable-shared --with-zlib=yes --with-bzip2=no --with-png=no --with-harfbuzz=no --with-brotli=no; make -j"$JOBS"; make install)
fi
if [[ ! -f "$PREFIX/lib/libharfbuzz.a" ]]; then
 cmake -S "$WORK/harfbuzz" -B "$WORK/harfbuzz/build" -DCMAKE_INSTALL_PREFIX="$PREFIX" -DCMAKE_OSX_DEPLOYMENT_TARGET=14.0 -DCMAKE_OSX_ARCHITECTURES=$ARCH -DCMAKE_BUILD_TYPE=Release -DBUILD_SHARED_LIBS=OFF -DHB_BUILD_SUBSET=OFF -DHB_BUILD_UTILS=OFF -DHB_HAVE_FREETYPE=OFF -DHB_HAVE_GLIB=OFF -DHB_HAVE_ICU=OFF
 cmake --build "$WORK/harfbuzz/build" -j"$JOBS";cmake --install "$WORK/harfbuzz/build"
fi
if [[ ! -f "$PREFIX/lib/libfribidi.a" ]]; then
 (cd "$WORK/fribidi"; ./configure --prefix="$PREFIX" --enable-static --disable-shared --disable-dependency-tracking;make -C lib -j"$JOBS";make -C lib install;make install-pkgconfigDATA)
fi
if [[ ! -f "$PREFIX/lib/libass.a" ]]; then
 (cd "$WORK/libass"; ./configure --prefix="$PREFIX" --enable-static --disable-shared --disable-fontconfig --enable-coretext --disable-asm;make -j"$JOBS";make install)
fi
mkdir -p "$ROOT/packaging/provenance/subtitles-$ARCH"
python3 - "$WORK" "$ROOT/packaging/provenance/subtitles-$ARCH" "$ROOT" <<'PY'
from pathlib import Path
import sys
source,out,root=Path(sys.argv[1]),Path(sys.argv[2]),sys.argv[3]
for name in ['freetype','harfbuzz','fribidi','libass']:
 for p in (source/name).rglob('*'):
  lower=p.name.lower()
  if p.is_file() and p.stat().st_size<2000000 and (any(x in lower for x in ['license','copying','copyright']) or lower in ['ftl.txt','config.log','cmakecache.txt']):
   label=name+'-'+str(p.relative_to(source/name)).replace('/','__')
   if len(label)<220:(out/label).write_text(p.read_text().replace(root,'${DISC_PORTER_SOURCE_ROOT}'))
PY
