#!/usr/bin/env python3

import argparse
import asteroid
import asteroid.app
from asteroid.module import *
from asteroid.wt import *

parser = argparse.ArgumentParser()
parser.add_argument(
    "-i", "--interactive",
    action="store_true",
    help="Drop to IPython shell instead of GLib event loop"
)
parser.add_argument(
    "-v", "--verbose",
    action="store_true",
    help="More verbose output"
)

args = parser.parse_args()

ADDRESS = "xx:xx:xx:xx:xx:xx"
API_KEY = 'XXXXXXXXXXXXXXXXXXXXXXX'
CITY_NAME = 'Moscow'


app = asteroid.app.App(ADDRESS, verbose=args.verbose)

app.register_module(ReconnectModule(timeout_base=10))
app.register_module(TimeSyncModule())
app.register_module(NotifyModule())
app.register_module(OWMModule(api_key=API_KEY, city=CITY_NAME))
app.register_module(MPDModule())

if args.interactive:
    import IPython
    IPython.embed()
else:
    app.run()
