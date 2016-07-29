#!/bin/sh
#SBATCH -o output
#SBATCH --nodes=3
#SBATCH --ntasks-per-node=24
mpirun sage script.py
