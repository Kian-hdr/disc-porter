"""Adjust MP4 text-track enabled flags to the explicit subtitle default policy.

FFmpeg's MP4 muxer enables the only subtitle track even with disposition 0.
The tkhd enabled flag is what FFprobe reads as default. This bounded in-place
metadata edit preserves all media bytes; the candidate is subsequently decoded,
probed and hashed before any publication.
"""
import os
import struct
from engine.core import ArchiveError


def boxes(f,start,end):
    offset=start
    while offset+8<=end:
        f.seek(offset);header=f.read(8)
        size,kind=struct.unpack('>I4s',header);length=8
        if size==1:
            raw=f.read(8)
            if len(raw)!=8:raise ArchiveError('Truncated MP4 large box')
            size=struct.unpack('>Q',raw)[0];length=16
        elif size==0:size=end-offset
        if size<length or offset+size>end:raise ArchiveError('Invalid MP4 box boundaries')
        yield kind,offset+length,offset+size
        offset+=size
    if offset!=end:raise ArchiveError('Trailing malformed MP4 box data')


def set_subtitle_defaults(path,flags):
    if not flags:return
    with open(path,'r+b')as f:
        end=os.fstat(f.fileno()).st_size;tracks=[]
        for kind,start,stop in boxes(f,0,end):
            if kind!=b'moov':continue
            for k,ts,te in boxes(f,start,stop):
                if k!=b'trak':continue
                tkhd=None;handler=None
                for key,bs,be in boxes(f,ts,te):
                    if key==b'tkhd':tkhd=bs
                    elif key==b'mdia':
                        for sub,ss,se in boxes(f,bs,be):
                            if sub==b'hdlr':f.seek(ss+8);handler=f.read(4)
                if handler in(b'sbtl',b'subt',b'text',b'clcp'):
                    if tkhd is None:raise ArchiveError('Subtitle track has no tkhd header')
                    tracks.append(tkhd)
        if len(tracks)!=len(flags):raise ArchiveError('MP4 subtitle metadata count mismatch')
        for position,default in zip(tracks,flags):
            f.seek(position);data=f.read(4)
            if len(data)!=4:raise ArchiveError('Truncated subtitle track flags')
            value=int.from_bytes(data[1:],'big');value=value|1 if default else value&~1
            f.seek(position+1);f.write(value.to_bytes(3,'big'))
        f.flush();os.fsync(f.fileno())
