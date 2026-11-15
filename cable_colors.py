"""Local visual cable preferences; never sent to the audio interface."""
import json
import os
from pathlib import Path
from routing_labels import SOURCE_LABELS,DESTINATION_LABELS

PALETTE=(('Red','#f04b4b'),('Orange','#ff942f'),('Yellow','#ffe04b'),('Green','#48ce68'),
         ('Cyan','#35d6e6'),('Blue','#427bff'),('Purple','#a16aee'),('Pink','#f26ab8'))
COLORS={color for name,color in PALETTE}
DEFAULT=PALETTE[4][1]


def config_path():
    return Path(os.environ.get('XDG_CONFIG_HOME',Path.home()/'.config'))/'af16rig-control'/'cable-colors.json'


class CableColors:
    def __init__(self):self.selected=DEFAULT;self.routes={}
    def choose(self,color):
        if color not in COLORS:raise ValueError('Unknown cable colour')
        self.selected=color
    def assign(self,source,destination,color):
        if source not in SOURCE_LABELS or destination not in DESTINATION_LABELS or color not in COLORS:raise ValueError('Invalid cable preference')
        self.routes[f'{source}:{destination}']=color
    def get(self,source,destination,fallback):return self.routes.get(f'{source}:{destination}',fallback)
    @classmethod
    def load(cls):
        result=cls()
        try:
            path=config_path()
            if path.stat().st_size>262144:return result
            value=json.loads(path.read_text())
            if not isinstance(value,dict):return result
            if value.get('selected') in COLORS:result.selected=value['selected']
            routes=value.get('routes',{})
            if isinstance(routes,dict):
                for key,color in routes.items():
                    try:
                        source,destination=map(int,key.split(':'));result.assign(source,destination,color)
                    except (ValueError,TypeError,AttributeError):continue
        except (OSError,ValueError,TypeError):pass
        return result
    def save(self):
        try:
            path=config_path();path.parent.mkdir(parents=True,exist_ok=True)
            path.write_text(json.dumps(dict(selected=self.selected,routes=self.routes),indent=2)+'\n')
            return True
        except OSError:return False
