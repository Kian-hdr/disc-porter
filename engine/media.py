"""Explicit SDR transforms and source-index stream selection."""
from fractions import Fraction
import re
from engine.core import ArchiveError, language, main_audio

TEXT={'subrip','ass','ssa','mov_text','webvtt','text'}

def number(value,default=1):
    try:return float(Fraction(str(value).replace(':','/')))
    except(ValueError,ZeroDivisionError):return default

def commentary(s):
    return bool(s.get('disposition',{}).get('comment'))or'commentary'in s.get('tags',{}).get('title','').lower()

def select_streams(probe,recipe,title):
    audio=[s for s in probe['streams']if s['codec_type']=='audio'];subs=[s for s in probe['streams']if s['codec_type']=='subtitle']
    for key,pool in [('audio_streams',audio),('subtitle_streams',subs),('forced_subtitle_streams',subs)]:
        if key in title and any(i not in {s['index']for s in pool}for i in title[key]):raise ArchiveError(key+' contains an index absent from the source')
    allowed=recipe['languages'];eligible=[s for s in audio if(not allowed or(language(s)or'und')in allowed)and(recipe['include_commentary']or not commentary(s))]
    if recipe['audio_policy']=='selected':
        if 'audio_streams'not in title:raise ArchiveError('Selected audio policy requires title audio_streams')
        selected=[s for s in audio if s['index']in title['audio_streams']]
    elif recipe['audio_policy']=='all':selected=eligible
    else:
        selected=[]
        for lang in dict.fromkeys(language(s)or'und'for s in eligible):
            matches=[s for s in eligible if(language(s)or'und')==lang]
            if lang=='und':selected.extend(matches)  # Unknown tags cannot establish that two tracks share a language.
            else:selected.append(max(matches,key=main_audio))
    # An explicit empty selected list is an intentional omission, recorded as a transform.
    preferred=recipe['default_audio_language']
    default_index=title.get('default_audio_stream')
    if default_index is not None and default_index not in {s['index']for s in selected}:raise ArchiveError('default_audio_stream must be a selected source audio index')
    def priority(s):
        if default_index is not None:return(s['index']!=default_index,s['index'])
        if preferred:return((language(s)or'und')!=preferred,s['index'])
        if allowed:return(allowed.index(language(s)or'und')if(language(s)or'und')in allowed else len(allowed),not bool(s.get('disposition',{}).get('default')),s['index'])
        return(not bool(s.get('disposition',{}).get('default')),s['index'])
    selected.sort(key=priority)
    if preferred and not any(language(s)==preferred for s in selected):raise ArchiveError('Requested default audio language is absent from selected source tracks')
    wanted=recipe['subtitle_languages'];chosen=[s for s in subs if not wanted or(language(s)or'und')in wanted]
    if'subtitle_streams'in title:chosen=[s for s in subs if s['index']in title['subtitle_streams']]
    if recipe['subtitle_policy']=='none':chosen=[]
    elif recipe['subtitle_policy']=='text':chosen=[s for s in chosen if s.get('codec_name')in TEXT]
    elif recipe['subtitle_policy']=='burn'and len(chosen)!=1:raise ArchiveError('Burn subtitles requires exactly one selected subtitle stream')
    if title.get('default_subtitle_stream')is not None and title['default_subtitle_stream']not in{s['index']for s in chosen}:raise ArchiveError('default_subtitle_stream must be a selected source subtitle index')
    if 'forced_subtitle_streams'in title and not set(title['forced_subtitle_streams'])<={s['index']for s in chosen}:raise ArchiveError('forced_subtitle_streams must refer to selected subtitle tracks')
    if recipe['default_subtitle_language']and chosen and not any(language(s)==recipe['default_subtitle_language']for s in chosen):raise ArchiveError('Default subtitle language absent from selected tracks')
    return selected,chosen,subs

def subtitle_flags(stream,position,mapped,recipe,title):
    if title.get('default_subtitle_stream')is not None:default=stream['index']==title['default_subtitle_stream']
    elif recipe['default_subtitle_language']:default=language(stream)==recipe['default_subtitle_language']and not any(language(prior)==recipe['default_subtitle_language']for prior in mapped[:position])
    else:default=bool(stream.get('disposition',{}).get('default'))
    forced=stream['index']in title['forced_subtitle_streams']if'forced_subtitle_streams'in title else bool(stream.get('disposition',{}).get('forced'))
    return default,forced

def build(probe,recipe,title,source,target,ffmpeg):
    videos=[s for s in probe['streams']if s['codec_type']=='video'and not s.get('disposition',{}).get('attached_pic')]
    if len(videos)!=1:raise ArchiveError('Multiple video/MVC streams require original archive mode')
    v=videos[0]
    hdr=v.get('color_transfer')in('smpte2084','arib-std-b67')or v.get('color_primaries')=='bt2020'or any('dovi'in str(d).lower()or'dolby'in str(d).lower()for d in v.get('side_data_list',[]))
    if hdr:raise ArchiveError('HDR/Dolby Vision transcode unsupported; use original archive mode')
    if v.get('pix_fmt')not in('yuv420p','yuv420p10le'):raise ArchiveError('Transcode supports SDR 4:2:0 8/10-bit only; choose original mode for this source')
    audio,subtitles,all_subs=select_streams(probe,recipe,title)
    filters=[];transforms=[];rate=number(v.get('r_frame_rate'),0)
    interlaced=v.get('field_order')not in(None,'unknown','progressive')
    deinterlace=recipe['deinterlace']
    if deinterlace in('frame','field')or(deinterlace=='auto'and interlaced):
        mode='send_field'if deinterlace=='field'else'send_frame'
        # auto uses per-frame interlace flags, rather than header alone.
        filters.append('bwdif=mode='+mode+':parity=auto:deint='+('interlaced'if deinterlace=='auto'else'all'))
        transforms.append(dict(kind='deinterlace',mode=deinterlace,evidence='source field_order '+str(v.get('field_order')),frame_rate_doubled=deinterlace=='field'))
        if deinterlace=='field':rate*=2
    width=v['width'];height=v['height'];sar=number(v.get('sample_aspect_ratio'))
    if recipe['aspect']=='square'and sar!=1:
        width=max(2,round(width*sar/2)*2);filters+=['scale='+str(width)+':'+str(height),'setsar=1'];sar=1
        transforms.append(dict(kind='aspect',mode='square',width=width,height=height))
    if recipe['resolution']!='source':
        target_height=int(recipe['resolution'][:-1]);display=width*sar/height
        if recipe['aspect']=='square':width=max(2,round(target_height*display/2)*2);sar=1
        else:width=max(2,round(target_height*width/height/2)*2)
        height=target_height;filters.append('scale='+str(width)+':'+str(height));filters.append('setsar='+str(sar))
        transforms.append(dict(kind='resolution',width=width,height=height,sample_aspect_ratio=sar))
    if recipe['frame_rate']!='source':rate=float(recipe['frame_rate']);filters.append('fps='+recipe['frame_rate']);transforms.append(dict(kind='frame_rate',target=rate))
    pix=v['pix_fmt']if recipe['bit_depth']=='source'else'yuv420p10le'if recipe['bit_depth']=='10'else'yuv420p'
    if pix!=v['pix_fmt']:transforms.append(dict(kind='bit_depth',source=v['pix_fmt'],target=pix))
    if recipe['video_codec']=='h264'and pix=='yuv420p10le':raise ArchiveError('H.264 compatibility output requires explicit bit_depth 8 for a 10-bit source')
    cmd=[ffmpeg,'-nostdin','-hide_banner','-v','warning','-progress','pipe:1','-stats_period','0.5','-n','-i',source]
    bitmap_burn=recipe['subtitle_policy']=='burn'and subtitles[0].get('codec_name')not in TEXT if subtitles else False
    if recipe['subtitle_policy']=='burn':
        s=subtitles[0]
        if bitmap_burn:
            cmd+=['-filter_complex','[0:'+str(v['index'])+'][0:'+str(s['index'])+']overlay[vburn]','-map','[vburn]']
            if filters:raise ArchiveError('Bitmap burn with additional video transforms requires original/text export or a separately reviewed composition')
        else:
            relative=[s2['index']for s2 in all_subs].index(s['index'])
            escaped=source.replace('\\','\\\\').replace(':','\\:').replace("'","'\\''")
            filters.append("subtitles=filename='"+escaped+"':si="+str(relative));cmd+=['-map','0:'+str(v['index'])]
        transforms.append(dict(kind='subtitle_burn',source_index=s['index']));mapped_sub=[]
    else:cmd+=['-map','0:'+str(v['index'])];mapped_sub=subtitles
    for s in audio:cmd+=['-map','0:'+str(s['index'])]
    for s in mapped_sub:cmd+=['-map','0:'+str(s['index'])]
    encoder=recipe['encoder'];codec=('hevc'if recipe['video_codec']=='hevc'else'h264')+'_videotoolbox'if encoder=='hardware'else'libx265'if recipe['video_codec']=='hevc'else'libx264'
    cmd+=['-c:v',codec,'-pix_fmt',pix]
    if encoder=='software':
        cmd+=['-preset',recipe['speed']]
        if recipe['bitrate_kbps']:cmd+=['-b:v',str(recipe['bitrate_kbps'])+'k']
        else:cmd+=['-crf',str(recipe['quality'])]
        if recipe['cpu_threads']:cmd+=['-threads',str(recipe['cpu_threads'])]
        if codec=='libx265':cmd+=['-x265-params',('pools='+str(recipe['cpu_threads'])+':'if recipe['cpu_threads']else'')+'log-level=error']
    else:cmd+=['-b:v',str(recipe['bitrate_kbps'])+'k','-allow_sw','0','-realtime','1'if recipe['speed']=='fast'else'0']
    if recipe['video_codec']=='hevc'and recipe['output_container']=='mp4':cmd+=['-tag:v','hvc1']
    if filters:cmd+=['-vf',','.join(filters)]
    for key,flag in [('color_range','-color_range'),('color_space','-colorspace'),('color_transfer','-color_trc'),('color_primaries','-color_primaries')]:
        if v.get(key)not in(None,'unknown'):cmd+=[flag,v[key]]
    cmd+=['-map_chapters','0']
    mapping=[]
    for i,s in enumerate(audio):
        codec=recipe['audio_codec'];channels=s.get('channels',0)if recipe['audio_channels']=='source'else min(s.get('channels',0),2)
        if codec=='copy'and recipe['output_container']=='mp4'and s.get('codec_name')not in('aac','ac3','eac3','alac','mp3'):raise ArchiveError('Selected original audio codec needs MKV or transcoded AAC/AC-3')
        if codec=='ac3'and(channels>6 or recipe['audio_bitrate_kbps']>640):raise ArchiveError('AC-3 supports up to 5.1 and 640 kbit/s; choose AAC or explicit stereo')
        cmd+=['-c:a:'+str(i),codec,'-metadata:s:a:'+str(i),'language='+(language(s)or'und'),'-disposition:a:'+str(i),'default'if i==0 else'0']
        if codec!='copy':cmd+=['-b:a:'+str(i),str(recipe['audio_bitrate_kbps'])+'k','-ac:a:'+str(i),str(channels)]
        mapping.append(dict(source_index=s['index'],language=language(s)or'und',channels=channels,codec=s['codec_name']if codec=='copy'else codec,default=i==0))
        if channels!=s.get('channels'):transforms.append(dict(kind='audio_channels',source_index=s['index'],source=s.get('channels'),target=channels))
    for i,s in enumerate(mapped_sub):
        codec='mov_text'if recipe['subtitle_policy']=='text'and recipe['output_container']=='mp4'else'copy'
        default,forced=subtitle_flags(s,i,mapped_sub,recipe,title)
        disp=(['default']if default else[])+(['forced']if forced else[])
        cmd+=['-c:s:'+str(i),codec,'-metadata:s:s:'+str(i),'language='+(language(s)or'und'),'-disposition:s:'+str(i),'+'.join(disp)or'0']
    if recipe['output_container']=='mp4':cmd+=['-movflags','+faststart']
    cmd+=[target]
    expected=dict(width=width,height=height,pix_fmt=pix,frame_rate=rate,sample_aspect_ratio=sar,progressive=deinterlace!='off'and(interlaced or deinterlace in('frame','field')),codec_name=recipe['video_codec'])
    return cmd,dict(expected_video=expected,audio_map=mapping,subtitle_map=[dict(source_index=s['index'],language=language(s)or'und',codec='mov_text'if recipe['output_container']=='mp4'and recipe['subtitle_policy']=='text'else s.get('codec_name'),forced=subtitle_flags(s,i,mapped_sub,recipe,title)[1],default=subtitle_flags(s,i,mapped_sub,recipe,title)[0])for i,s in enumerate(mapped_sub)],transforms=transforms,bitmap_subtitles=sum(s.get('codec_name')not in TEXT for s in all_subs),subtitle_burn=recipe['subtitle_policy']=='burn',source_video_index=v['index'])
