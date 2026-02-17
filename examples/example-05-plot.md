### Radial Basis Functions (RBF kernels)

```plot:
xs = np.linspace(0, 4, 100)
plt.plot(xs, np.exp(-xs**2), label="Gaussian")
plt.plot(xs, np.exp(-xs), label="Exponential")
plt.xlabel("Reduced distance $d/\sigma$")
plt.ylabel("Kernel value")
plt.legend()
```
