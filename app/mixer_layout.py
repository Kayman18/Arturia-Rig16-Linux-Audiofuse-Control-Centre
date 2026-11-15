"""Mixer source ordering and widths, independent of device state."""
def bank_sources(start, bus='main'):
    sources=list(range(start,start+16))
    if start==1 and bus=='main':sources.extend((33,34))
    return sources

def strip_widths(width,count,master_minimum=170):
    count=max(1,count)
    available=max(count+1,width-5-3*count)
    master=min(available-count,max(master_minimum,available//(count+1)))
    base,extra=divmod(available-master,count)
    return [base+(i<extra) for i in range(count)],master

# Fixed logical pixels; desktop DPI remains controlled by Tk / the OS.
def fixed_geometry(count,master_minimum=164):
    strip=max(164,master_minimum)
    return strip,strip*(max(1,count)+1)+3*max(1,count)+5,850,52

def expanded_geometry(width,height,count,minimum=164,fit=False):
    """Use spare viewport pixels without scaling the controls themselves.

    Count includes channels and the two output strips before Main Master.
    """
    count=max(1,count)
    total=max(int(width),(count+1)+3*count+5) if fit else max(int(width),minimum*(count+1)+3*count+5)
    available=total-3*count-5
    base,extra=divmod(available,count+1)
    widths=[base+(i<extra) for i in range(count+1)]
    return widths,total,max(850,int(height)),52
