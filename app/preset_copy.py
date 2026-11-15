"""Copy stored settings via the verified load then save operations.

This deliberately changes the live mix. Destination name is retained.
There is no guessed copy opcode, retry, or automatic rollback.
"""
from af16rig import DeviceError,DeviceDisconnected
from device_presets import check_slot,check_device,read_slot,operate

def copy_slot(device,source,destination,source_name,destination_name,expected_status,on_load=None,between=None):
    check_slot(source);check_slot(destination,saving=True);check_device(device)
    if source==destination:raise ValueError('Choose a different destination slot')
    if not isinstance(source_name,str) or not isinstance(destination_name,str):
        raise ValueError('Both captured preset names are required')
    stage='preflight';loaded=False
    try:
        if read_slot(device,destination)['name']!=destination_name:
            raise DeviceError('Destination preset name changed; read presets again')
        stage='load source'
        loaded_result=operate(device,'load',source,source_name,expected_status,on_load)
        loaded=True
        stage='save destination'
        if between:between()
        saved=operate(device,'save',destination,destination_name,loaded_result['status'])
        return dict(action='copy',source=source,slot=destination,status=saved['status'],
                    demo=saved['demo'],write_requests=loaded_result['write_requests']+saved['write_requests'],
                    destination_name=destination_name)
    except (DeviceError,OSError) as error:
        detail=('Source load was confirmed; active settings have changed. ' if loaded else
                'Source load was not confirmed; inspect the rig before retrying. ' if stage=='load source' else '')
        message=f'Preset copy stopped during {stage}. '+detail+str(error)+' No automatic retry or rollback.'
        if isinstance(error,DeviceDisconnected):raise DeviceDisconnected(message) from error
        raise DeviceError(message) from error
