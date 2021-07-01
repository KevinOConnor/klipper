# This script instals the prerequisites for measureing resonances on a standard, single instance install of Klippy

# Step 1: Install numpy in the virtualenv so it can be used by Klippy
# If you run multiple instances of Klippy in their own virtualenvs, you'll need
# to install numpy in every instance you want to run resonance measureing in
~/klippy-env/bin/pip install -v numpy

# Step 2: Install numpy and matplotlib system-wide
sudo apt update
sudo apt install python-numpy python-matplotlib
