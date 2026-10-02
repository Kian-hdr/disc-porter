"""Remove private build roots from FFmpeg's displayed configuration metadata only.

Runtime compiler flags are untouched. Preserve header mtime and rebuild exactly the
translation units that consume FFMPEG_CONFIGURATION, so unrelated objects remain valid.
"""
import os
from pathlib import Path
import sys
source = Path(sys.argv[1]); root = sys.argv[2]
header = source / 'config.h'; before = header.read_text(); info = header.stat()
after = before.replace(root, '${DISC_PORTER_SOURCE_ROOT}')
if before != after:
    header.write_text(after); os.utime(header, ns=(info.st_atime_ns,info.st_mtime_ns))
    paths = [source/'fftools/ffprobe.c',source/'fftools/opt_common.c']
    paths += [source/lib/'version.c' for lib in ['libavutil','libavcodec','libavformat','libavdevice','libavfilter','libswscale','libswresample']]
    for p in paths: os.utime(p,None)
