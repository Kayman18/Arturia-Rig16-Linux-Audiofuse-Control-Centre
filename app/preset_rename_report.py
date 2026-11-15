"""Read-only raw preset-name capture; bounded to the 12-byte slot field."""
from af16rig import DemoAF16Rig,DeviceDisconnected

def capture(device,slot):
    if isinstance(device,DemoAF16Rig):return {'demo':True}
    from device_presets import read_word
    result={'passes':[]}
    for _ in range(2):
        words=[]
        try:
            for index in range(6):words.append(read_word(device,slot+9,index))
        except DeviceDisconnected:raise
        except Exception as error:
            result['error']=str(error)
        raw=b''.join(w.to_bytes(2,'little') for w in words)
        result['passes'].append(dict(words=words,hex=raw.hex(),text_before_null=raw.split(b'\0',1)[0].decode('utf-8',errors='replace')))
        if 'error' in result:break
    result['stable']=len(result['passes'])==2 and result['passes'][0]['words']==result['passes'][1]['words']
    return result
