"""Versioned local recipe schema. No provider secrets are stored here."""
from copy import deepcopy

ENGINE_VERSION='0.2.0'
DEFAULTS=dict(schema_version=2,revision=1,preset_id='balanced',mode='transcode',video_codec='hevc',quality=20,languages=[],output_container='mp4',encoder='software',speed='medium',bitrate_kbps=0,bit_depth='source',resolution='source',frame_rate='source',deinterlace='auto',aspect='preserve',output_root='',work_root='',original_root='',folder_layout='organized',file_template='{title}',reserve_bytes=1000000000,audio_policy='main_per_language',audio_codec='aac',audio_bitrate_kbps=384,audio_channels='source',include_commentary=False,default_audio_language='',preserve_original_audio=True,subtitle_policy='text',subtitle_languages=[],default_subtitle_language='',preserve_bitmap_subtitles=True,auto_start=False,default_checkpoint='complete',on_battery='pause',auto_resume=True,retry_count=2,max_encoders=1,cpu_threads=0,cleanup_policy='keep',notifications=True,online_lookup=False,appearance='system',ffmpeg_path='',ffprobe_path='',makemkv_path='')
ENUMS=dict(preset_id=['balanced','compatibility','original','legacy'],mode=['transcode','original'],video_codec=['hevc','h264'],output_container=['mp4','mkv'],encoder=['software','hardware'],speed=['ultrafast','superfast','veryfast','faster','fast','medium','slow','slower','veryslow'],bit_depth=['source','8','10'],resolution=['source','480p','720p','1080p','2160p'],frame_rate=['source','24','25','30','50','60'],deinterlace=['auto','off','frame','field'],aspect=['preserve','square'],folder_layout=['organized','flat'],audio_policy=['main_per_language','all','selected'],audio_codec=['aac','ac3','copy'],audio_channels=['source','stereo'],subtitle_policy=['text','copy','burn','none'],on_battery=['pause','run'],cleanup_policy=['keep','delete_verified'],appearance=['system','light','dark'],default_checkpoint=['scan','acquire','encode','verify','complete'])
LIMITS=dict(quality=(0,51),bitrate_kbps=(0,200000),audio_bitrate_kbps=(32,1536),reserve_bytes=(0,1000000000000000),retry_count=(0,10),max_encoders=(1,1),cpu_threads=(0,__import__('os').cpu_count() or 1))
NON_RECIPE={'schema_version','revision','preset_id','output_root','work_root','original_root','auto_start','default_checkpoint','on_battery','auto_resume','retry_count','max_encoders','notifications','online_lookup','appearance','ffmpeg_path','ffprobe_path','makemkv_path'}
RECIPE=set(DEFAULTS)-NON_RECIPE
BUILTINS={
 'balanced':dict(DEFAULTS),
 'compatibility':dict(DEFAULTS,video_codec='h264',bit_depth='8'),
 'original':dict(DEFAULTS,mode='original',output_container='mkv',audio_codec='copy',subtitle_policy='copy'),
 'legacy':dict(DEFAULTS,quality=18,languages=['eng','deu'],deinterlace='off'),
}

def settings_schema():
    schema={}
    for key,val in DEFAULTS.items():
        typ='boolean' if type(val) is bool else 'integer' if type(val) is int else 'array' if isinstance(val,list) else 'string'
        item=dict(type=typ,default=deepcopy(val))
        if key in ENUMS and key!='preset_id':item['enum']=ENUMS[key]
        if key in LIMITS:item.update(minimum=LIMITS[key][0],maximum=LIMITS[key][1])
        schema[key]=item
    return schema


def validate(values, patch=False, recipe=False):
    import re
    from engine.core import ArchiveError
    allowed=RECIPE if recipe else set(DEFAULTS)
    if set(values)-allowed:raise ArchiveError('Unknown or non-recipe settings: '+', '.join(sorted(set(values)-allowed)))
    result=dict(values)
    for k,v in values.items():
        d=DEFAULTS[k]
        if type(v) is not type(d):raise ArchiveError(k+' must be '+settings_schema()[k]['type'])
        if k in ENUMS and k!='preset_id' and v not in ENUMS[k]:raise ArchiveError(k+' must be one of '+', '.join(ENUMS[k]))
        if k in LIMITS and not LIMITS[k][0]<=v<=LIMITS[k][1]:raise ArchiveError(k+' outside supported range')
        if k in ('languages','subtitle_languages') and (len(v)!=len(set(v)) or any(not isinstance(x,str) or not re.fullmatch('[a-z]{3}',x) for x in v)):raise ArchiveError(k+' must contain unique three-letter language codes; empty means all')
        if k in ('default_audio_language','default_subtitle_language') and v and not re.fullmatch('[a-z]{3}',v):raise ArchiveError(k+' requires a three-letter language code or empty')
    if not patch:
        if values['encoder']=='hardware' and values['mode']=='transcode' and not values['bitrate_kbps']:raise ArchiveError('Hardware encoding needs explicit bitrate_kbps greater than zero')
        if values['audio_codec']=='copy' and values['audio_channels']!='source':raise ArchiveError('Audio copy cannot downmix; use AAC or AC-3 for stereo')
        if values['subtitle_policy']=='copy' and values['output_container']=='mp4' and values['mode']!='original':raise ArchiveError('Subtitle copy needs MKV; choose text for MP4')
        if values['video_codec']=='h264' and values['bit_depth']=='10' and values['mode']=='transcode':raise ArchiveError('H.264 compatibility export requires 8-bit or supported source depth')
        if values['cleanup_policy']=='delete_verified' and not (values['preserve_original_audio'] and values['preserve_bitmap_subtitles']):raise ArchiveError('delete_verified requires original audio and bitmap subtitle preservation; enable both preservation flags or choose Keep')
        if values['mode']=='original' and values['cleanup_policy']!='keep':raise ArchiveError('Original archive deliverables are retained; select cleanup_policy keep')
        if values['encoder']=='hardware' and values['speed'] not in ('fast','medium','slow'):raise ArchiveError('Hardware speed supports fast, medium or slow')
        template=values['file_template']
        try:template.format(title='Title',collection='Collection',season=1,episode=1,year=2000)
        except (ValueError,KeyError,IndexError):raise ArchiveError('File template supports title, collection, season, episode and year only')
        if '/' in template or '\\' in template or not template.strip():raise ArchiveError('File template must be a filename component')
    return result


def builtins():
    return [dict(id=k,name={'balanced':'Balanced','compatibility':'Compatibility','original':'Original archive','legacy':'Legacy'}[k],builtin=True,revision=1,settings={f:deepcopy(v[f]) for f in RECIPE}) for k,v in BUILTINS.items()]
