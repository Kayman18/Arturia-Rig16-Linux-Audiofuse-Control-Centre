"""Serializable, read-only capture of every decoded meter tap."""
import math
from datetime import datetime,timezone
from meter_bridge import BANKS,label

def dbfs(value):
    # JSON null means silence/no value; linear amplitude distinguishes the two.
    return 20*math.log10(value) if value is not None and value > 0 else None

def capture(session,names,now,*,demo=False,held=False):
    fresh=session.fresh(now)
    rows=[]
    for bank,keys in BANKS.items():
        for key in keys:
            current=session.frame.get(key) if session.frame else None
            peak=session.peaks.get(key)
            rows.append(dict(bank=bank,group=key[0],index=key[1],label=label(key,names),
                last_linear=current,last_dbfs=dbfs(current),peak_linear=peak,
                peak_dbfs=dbfs(peak),observed_full_scale=key in session.full_scale))
    return dict(format='AF16Rig meter snapshot',version=1,
        exported_utc=datetime.now(timezone.utc).isoformat(),demo=bool(demo),held=bool(held),
        connection_serial=session.serial,fresh_at_capture=fresh,
        frame_age_seconds=None if session.time is None else max(0,now-session.time),
        notes='All 118 taps. Zero linear amplitude means silence; null means unavailable. '
              'Stale last readings and retained peaks are historical. Peaks are observed '
              'meter-frame maxima, not true-peak measurements. Indices are zero-based.',
        readings=rows)
