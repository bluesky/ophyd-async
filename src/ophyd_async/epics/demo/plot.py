import matplotlib.pyplot as plt
import numpy as np

delta = 0.025
x = y = np.arange(-5.0, 5.0, delta)
X, Y = np.meshgrid(x, y)
fig, ax = plt.subplots(nrows=3, ncols=2)

for channel, row in zip([1, 2, 3], ax, strict=False):
    for offset, col in zip([10, 100], row, strict=False):
        Z = np.sin(X) ** channel + np.cos(X * Y + offset) + 2
        print(Z.min(), Z.max())
        im = col.imshow(
            Z,
            interpolation="bilinear",
            origin="lower",
            extent=(-10, 10, -10, 10),
            vmax=4,
            vmin=0,
        )

if __name__ == "__main__":
    plt.show()
