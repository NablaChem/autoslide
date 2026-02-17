
### Kernel Ridge Regression (KRR)

$$\mathbf{K}_{ij} = {k}(\mathbf{x}_i, \mathbf{x}_j)$$
[[ {k} ]] Kernel function
[[ \mathbf{x}_i, \mathbf{x}_j ]] Features of training points
[[ \mathbf{K}_{ij} ]] Kernel matrix element

$$\mathbf{w} = (\mathbf{K} + \lambda\, \mathbf{I}_N)^{-1}\mathbf{y}$$
[[ \mathbf{K} ]] Kernel matrix ($N\times N$)
[[ \mathbf{w} ]] Model weights
[[ \lambda ]] Regularization
[[ \mathbf{I}_N ]] Identity matrix ($N\times N$)
[[ \mathbf{y} ]] Training labels

$$\hat y(\mathbf{x}_q) = \sum_{i=1}^{ N } w_i {k}(\mathbf{x}_i, \mathbf{x}_q)$$
[[ \hat y ]] Prediction
[[ \mathbf{x}_q ]] Query
[[ w_i ]] Weight of $i$-th training point
[[ \mathbf{x}_i ]] Training point features