#generate a colorbar
import matplotlib.pyplot as plt
import matplotlib as mpl
import argparse

a = argparse.ArgumentParser()
a.add_argument("--units", required=True, help="Units to display")
a.add_argument("--max", default=1, type=float, help="Max unit")
args = a.parse_args()

mpl.rcParams.update({'font.size': 18})

fig, ax = plt.subplots(figsize=(6, 1), layout='constrained')

cmap = mpl.cm.magma
norm = mpl.colors.Normalize(vmin=0, vmax=args.max)

fig.colorbar(mpl.cm.ScalarMappable(norm=norm, cmap=cmap),
             cax=ax, orientation='horizontal', label=args.units)

plt.savefig("colorbar.pdf")
