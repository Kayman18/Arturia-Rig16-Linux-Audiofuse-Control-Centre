"""Nonblocking reconnect backoff. Reconnection never represents a write retry."""

class ReconnectPolicy:
    DELAYS=(1,2,5,10,30)
    def __init__(self):self.enabled=True;self.wanted=False;self.failures=0;self.deadline=None
    def start(self):self.wanted=True;self.failures=0;self.deadline=None
    def stop(self):self.wanted=False;self.failures=0;self.deadline=None
    def success(self):self.failures=0;self.deadline=None
    def failed(self,now):
        self.deadline=None
        if not self.enabled or not self.wanted:return None
        delay=self.DELAYS[min(self.failures,len(self.DELAYS)-1)];self.failures+=1;self.deadline=now+delay
        return delay
    def due(self,now):return self.enabled and self.wanted and self.deadline is not None and now>=self.deadline
    def set_enabled(self,value):
        self.enabled=bool(value)
        if not self.enabled:self.deadline=None

# Settings and read-only requests may survive connection changes. Everything
# else is discarded, so new write commands cannot accidentally escape a review.
CONTROL_COMMANDS={'connect','disconnect','auto_reconnect','input_select','meters_enable','preamp_enable'}
READ_COMMANDS={'midi_ports_read','scene_read','phones_read','midi_read','console_read','masters_read','routing_capture','name_read','preset_read','preset_status','clock_refresh','record_pan','phones_record'}
