# Utility to read and resize the Klipper logo.
#
# Copyright (C) 2021  Matthew Lloyd <github@matthewlloyd.net>
#
# This file may be distributed under the terms of the GNU GPLv3 license.
import os
from PIL import Image

LOGO_IMAGE = None

def make_logo(width):
    global LOGO_IMAGE
    if LOGO_IMAGE is None:
        LOGO_IMAGE = Image.open(
            os.path.join(os.path.dirname(__file__),
                         '../../../docs/img/klipper-logo.png'))
    new_height = int(LOGO_IMAGE.height / float(LOGO_IMAGE.width) * width)
    return LOGO_IMAGE.resize((width, new_height), resample=Image.LANCZOS)
