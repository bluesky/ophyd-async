import matplotlib.cbook as cbook
import matplotlib.cm as cm
import matplotlib.pyplot as plt
import numpy as np
from matplotlib.patches import PathPatch
from matplotlib.path import Path

delta = 0.025
x = y = np.arange(-10.0, 10.0, delta)
X, Y = np.meshgrid(x, y)
Z = (2 + np.sin(X) ** 10 + np.cos(100 + Y * X) * np.cos(X)) * 999
print(Z.max(), Z.min())
fig, ax = plt.subplots()
im = ax.imshow(
    Z,
    interpolation="bilinear",
    cmap=cm.RdYlGn,
    origin="lower",
    extent=(-10, 10, -10, 10),
    vmax=abs(Z).max(),
    vmin=-abs(Z).max(),
)

if __name__ == "__main__":
    plt.show()
