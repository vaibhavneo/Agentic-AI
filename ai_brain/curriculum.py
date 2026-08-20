"""A curriculum for the AI Brain: the spine its answers stand on.

The retrieval layer reads the user's own 17 shelves. That works beautifully on
the machine holding the books and not at all on a deployed box, where the
indexes do not exist — and it degrades quietly, so the app looks fine while
answering from nothing.

This module is the fix. Each topic is a compact, checkable statement of what
the subject actually is: its intuition, the concepts that name it, and the
equations that carry it. Topics are first-class citable sources, tagged
[C:topic-id], exactly like a retrieved passage. Losing the shelves then costs
breadth, not grounding.

The equations are the point. A summary that says "attention weighs tokens by
similarity" is a slogan; one that carries softmax(QKᵀ/√d_k)V can be reasoned
from, and can be checked.
"""
from __future__ import annotations

import math
import re
from dataclasses import dataclass
from typing import Dict, List

LEVELS = ["foundations", "core", "advanced", "frontier"]


@dataclass(frozen=True)
class Topic:
    id: str
    title: str
    level: str
    prerequisites: List[str]
    key_concepts: List[str]
    key_equations: List[str]
    intuition: str
    shelves: List[str]


TOPICS: Dict[str, Topic] = {t.id: t for t in [

    # ── foundations: the mathematics everything else is written in ────────
    Topic(
        id="vectors-and-matrices",
        title="Vectors, Matrices and Linear Maps",
        level="foundations",
        prerequisites=[],
        key_concepts=["vector space", "linear map", "matrix multiplication",
                      "rank", "null space", "basis", "inner product", "norm"],
        key_equations=[r"(AB)_{ij} = \sum_k A_{ik}B_{kj}",
                       r"\langle x, y \rangle = x^\top y",
                       r"\|x\|_2 = \sqrt{x^\top x}",
                       r"\operatorname{rank}(A) + \dim\ker(A) = n"],
        intuition="A matrix is not a grid of numbers, it is a function that takes "
                  "vectors to vectors and does so linearly. Every question about a "
                  "matrix — is it invertible, what does it stretch, what does it "
                  "destroy — is a question about that function. Rank counts the "
                  "dimensions that survive the map; the null space is what gets "
                  "crushed to zero.",
        shelves=["desk-mathematics", "desk-mathematics-for-machine-learning-and-deep-learning"],
    ),
    Topic(
        id="matrix-decompositions",
        title="Eigendecomposition and the SVD",
        level="foundations",
        prerequisites=["vectors-and-matrices"],
        key_concepts=["eigenvalue", "eigenvector", "SVD", "singular value decomposition",
                      "spectral theorem", "condition number", "low-rank approximation"],
        key_equations=[r"A v = \lambda v",
                       r"A = U \Sigma V^\top",
                       r"A = Q \Lambda Q^\top \quad (A = A^\top)",
                       r"\kappa(A) = \sigma_{\max}/\sigma_{\min}"],
        intuition="Every matrix, square or not, is a rotation, then a scaling along "
                  "axes, then another rotation — that is the SVD. The singular values "
                  "say how much each direction is stretched, so the largest few carry "
                  "most of the map: keep them and you have the best low-rank "
                  "approximation there is. The condition number, the ratio of largest "
                  "to smallest, is why some linear systems are hopeless in floating point.",
        shelves=["desk-mathematics", "desk-mathematics-for-machine-learning-and-deep-learning"],
    ),
    Topic(
        id="probability-foundations",
        title="Probability, Random Variables and Expectation",
        level="foundations",
        prerequisites=[],
        key_concepts=["sample space", "random variable", "probability density",
                      "expectation", "variance", "independence", "joint distribution",
                      "marginalisation"],
        key_equations=[r"\mathbb{E}[X] = \int x\, p(x)\, dx",
                       r"\operatorname{Var}(X) = \mathbb{E}[X^2] - \mathbb{E}[X]^2",
                       r"p(x) = \int p(x, y)\, dy",
                       r"\mathbb{E}[aX + bY] = a\mathbb{E}[X] + b\mathbb{E}[Y]"],
        intuition="Probability is bookkeeping for uncertainty. Expectation is the "
                  "long-run average, and it is linear whether or not the variables are "
                  "independent — a fact that does more work in machine learning than "
                  "any other single identity. Variance is not linear, which is why "
                  "independence keeps mattering.",
        shelves=["desk-mathematics", "desk-data-science"],
    ),
    Topic(
        id="bayes-rule",
        title="Bayes' Rule and Inference",
        level="foundations",
        prerequisites=["probability-foundations"],
        key_concepts=["prior", "likelihood", "posterior", "evidence",
                      "conjugate prior", "MAP estimate", "Bayesian updating"],
        key_equations=[r"p(\theta \mid D) = \frac{p(D \mid \theta)\, p(\theta)}{p(D)}",
                       r"p(D) = \int p(D \mid \theta) p(\theta)\, d\theta",
                       r"\hat{\theta}_{\text{MAP}} = \arg\max_\theta p(D\mid\theta)p(\theta)"],
        intuition="Bayes' rule is how a belief changes when evidence arrives. The "
                  "prior is what you thought, the likelihood is how well each "
                  "hypothesis explains what you saw, and the posterior is the "
                  "reconciliation. Almost every regulariser in machine learning is a "
                  "prior wearing a disguise.",
        shelves=["desk-mathematics", "desk-machine-learning", "desk-data-science"],
    ),
    Topic(
        id="information-theory",
        title="Entropy, Cross-Entropy and KL Divergence",
        level="foundations",
        prerequisites=["probability-foundations"],
        key_concepts=["Shannon entropy", "cross-entropy", "KL divergence",
                      "mutual information", "perplexity", "coding length"],
        key_equations=[r"H(p) = -\sum_i p_i \log p_i",
                       r"H(p, q) = -\sum_i p_i \log q_i",
                       r"D_{\mathrm{KL}}(p \parallel q) = \sum_i p_i \log \frac{p_i}{q_i}",
                       r"H(p,q) = H(p) + D_{\mathrm{KL}}(p\parallel q)",
                       r"\text{PPL} = \exp(H)"],
        intuition="Entropy is the average number of bits you must spend to describe "
                  "a draw from a distribution. Cross-entropy is what you spend when "
                  "you encode using the wrong distribution, and KL is the excess — "
                  "which is why it is never negative and zero only when you are "
                  "right. Training a language model on cross-entropy loss is "
                  "literally minimising the description length of the corpus, and "
                  "perplexity is that loss exponentiated back into 'effective number "
                  "of choices'.",
        shelves=["desk-mathematics", "desk-machine-learning", "desk-llms"],
    ),
    Topic(
        id="calculus-and-gradients",
        title="Derivatives, Jacobians and the Chain Rule",
        level="foundations",
        prerequisites=["vectors-and-matrices"],
        key_concepts=["partial derivative", "gradient", "Jacobian", "Hessian",
                      "chain rule", "directional derivative", "Taylor expansion"],
        key_equations=[r"\nabla f = \left(\tfrac{\partial f}{\partial x_1}, \dots, \tfrac{\partial f}{\partial x_n}\right)^\top",
                       r"J_{ij} = \frac{\partial f_i}{\partial x_j}",
                       r"\frac{\partial}{\partial x}(g \circ f) = J_g \, J_f",
                       r"f(x+\delta) \approx f(x) + \nabla f^\top \delta + \tfrac{1}{2}\delta^\top H \delta"],
        intuition="The gradient points in the direction of steepest increase, and its "
                  "length says how steep. For a function of many variables the "
                  "derivative is a matrix — the Jacobian — and the chain rule becomes "
                  "matrix multiplication. That single fact is the whole of "
                  "backpropagation; everything else is bookkeeping about which order "
                  "to multiply in.",
        shelves=["desk-mathematics", "desk-mathematics-for-machine-learning-and-deep-learning"],
    ),
    Topic(
        id="convexity-and-optimization",
        title="Convexity and the Shape of Optimisation",
        level="foundations",
        prerequisites=["calculus-and-gradients"],
        key_concepts=["convex set", "convex function", "global minimum",
                      "saddle point", "Lagrange multiplier", "duality",
                      "constrained optimisation"],
        key_equations=[r"f(\lambda x + (1-\lambda)y) \le \lambda f(x) + (1-\lambda) f(y)",
                       r"\nabla^2 f \succeq 0 \iff f \text{ convex}",
                       r"\mathcal{L}(x,\lambda) = f(x) + \sum_i \lambda_i g_i(x)"],
        intuition="Convex problems have one basin, so any local minimum is the "
                  "answer and you can stop worrying. Neural networks are not convex, "
                  "and the interesting empirical fact is that it mostly does not "
                  "matter: in high dimensions the troublesome critical points are "
                  "overwhelmingly saddles rather than bad local minima, and gradient "
                  "noise escapes saddles.",
        shelves=["desk-mathematics", "desk-machine-learning"],
    ),
    Topic(
        id="gradient-descent",
        title="Gradient Descent and Its Convergence",
        level="foundations",
        prerequisites=["calculus-and-gradients", "convexity-and-optimization"],
        key_concepts=["learning rate", "step size", "convergence rate",
                      "condition number", "stochastic gradient descent",
                      "batch size", "learning rate schedule"],
        key_equations=[r"x_{t+1} = x_t - \eta \nabla f(x_t)",
                       r"\eta < 2/L \quad (L\text{-smooth})",
                       r"x_{t+1} = x_t - \eta \nabla f_{i_t}(x_t) \quad (\text{SGD})"],
        intuition="Walk downhill, repeat. The whole art is the step size: too small "
                  "and you never arrive, too large and you bounce out of the valley. "
                  "For a quadratic the safe ceiling is set by the largest curvature, "
                  "while the speed of progress is set by the smallest — so the "
                  "condition number, the ratio of the two, decides how painful the "
                  "problem is. Stochastic gradients trade exactness for cheapness, "
                  "and the resulting noise turns out to help.",
        shelves=["desk-machine-learning", "desk-deep-learning", "desk-mathematics"],
    ),
    Topic(
        id="numerical-stability",
        title="Floating Point and Numerical Stability",
        level="foundations",
        prerequisites=["vectors-and-matrices"],
        key_concepts=["floating point", "catastrophic cancellation", "log-sum-exp",
                      "overflow", "underflow", "epsilon", "mixed precision"],
        key_equations=[r"\log \sum_i e^{x_i} = m + \log \sum_i e^{x_i - m},\; m = \max_i x_i",
                       r"\mathrm{softmax}(x)_i = \frac{e^{x_i - m}}{\sum_j e^{x_j - m}}"],
        intuition="Mathematics is exact and computers are not. Exponentials overflow, "
                  "nearly-equal subtractions lose every significant digit, and a "
                  "correct formula can be a broken program. The log-sum-exp shift is "
                  "the canonical fix and it is everywhere in machine learning — every "
                  "softmax you have ever run subtracted the max first, whether or not "
                  "the textbook mentioned it.",
        shelves=["desk-computer-science", "desk-python", "desk-deep-learning"],
    ),

    # ── core: classical machine learning ──────────────────────────────────
    Topic(
        id="supervised-learning",
        title="The Supervised Learning Setup",
        level="core",
        prerequisites=["probability-foundations"],
        key_concepts=["training set", "hypothesis class", "empirical risk",
                      "generalisation", "i.i.d. assumption", "train-test split",
                      "inductive bias"],
        key_equations=[r"\hat{R}(h) = \frac{1}{n}\sum_{i=1}^n \ell(h(x_i), y_i)",
                       r"R(h) = \mathbb{E}_{(x,y)\sim \mathcal{D}}[\ell(h(x), y)]"],
        intuition="You minimise error on data you have, and hope it transfers to data "
                  "you do not. Everything difficult in machine learning lives in that "
                  "'hope': the gap between empirical and true risk. The i.i.d. "
                  "assumption is what licenses the hope, and it is violated constantly "
                  "in practice.",
        shelves=["desk-machine-learning", "desk-data-science"],
    ),
    Topic(
        id="bias-variance",
        title="Bias, Variance and Overfitting",
        level="core",
        prerequisites=["supervised-learning"],
        key_concepts=["bias", "variance", "irreducible error", "overfitting",
                      "underfitting", "model capacity", "double descent"],
        key_equations=[r"\mathbb{E}[(y - \hat{f})^2] = \mathrm{Bias}[\hat f]^2 + \mathrm{Var}[\hat f] + \sigma^2"],
        intuition="Error splits three ways: being systematically wrong, being "
                  "unstably right, and noise you can never beat. Simple models are "
                  "biased, flexible models are high-variance, and the classical advice "
                  "is to sit at the sweet spot. Modern overparameterised networks "
                  "cheerfully violate the classical picture — past the interpolation "
                  "threshold test error falls again, the double-descent curve — which "
                  "is a good reminder that the decomposition is a description, not a law.",
        shelves=["desk-machine-learning", "desk-deep-learning"],
    ),
    Topic(
        id="regularization",
        title="Regularisation",
        level="core",
        prerequisites=["bias-variance"],
        key_concepts=["L1 penalty", "L2 penalty", "weight decay", "sparsity",
                      "early stopping", "data augmentation", "MAP interpretation"],
        key_equations=[r"J(w) = \hat{R}(w) + \lambda \|w\|_2^2",
                       r"J(w) = \hat{R}(w) + \lambda \|w\|_1",
                       r"w_{t+1} = (1 - \eta\lambda) w_t - \eta \nabla \hat{R}(w_t)"],
        intuition="Regularisation is a thumb on the scale against complexity. L2 "
                  "shrinks everything smoothly and corresponds to a Gaussian prior; L1 "
                  "drives coefficients exactly to zero and corresponds to a Laplace "
                  "prior, which is why it selects features. Early stopping is a "
                  "regulariser too, just an implicit one.",
        shelves=["desk-machine-learning", "desk-deep-learning"],
    ),
    Topic(
        id="linear-and-logistic-regression",
        title="Linear and Logistic Regression",
        level="core",
        prerequisites=["supervised-learning", "calculus-and-gradients"],
        key_concepts=["least squares", "normal equations", "sigmoid", "log-odds",
                      "decision boundary", "maximum likelihood"],
        key_equations=[r"\hat{w} = (X^\top X)^{-1} X^\top y",
                       r"\sigma(z) = \frac{1}{1 + e^{-z}}",
                       r"\ell(w) = -\sum_i \left[y_i \log \hat{p}_i + (1-y_i)\log(1-\hat{p}_i)\right]",
                       r"\nabla_w \ell = X^\top(\hat{p} - y)"],
        intuition="Linear regression has a closed form because the loss is a "
                  "quadratic bowl. Logistic regression does not, because squashing "
                  "through a sigmoid destroys that — but its loss is still convex, so "
                  "gradient descent always finds the global optimum. Notice the "
                  "gradient of the logistic loss is the same shape as the linear one: "
                  "features times residual. That is not a coincidence, it is what "
                  "generalised linear models share.",
        shelves=["desk-machine-learning", "desk-data-science"],
    ),
    Topic(
        id="maximum-likelihood",
        title="Maximum Likelihood and Loss Functions",
        level="core",
        prerequisites=["probability-foundations", "information-theory"],
        key_concepts=["likelihood", "log-likelihood", "MLE", "MSE from Gaussian",
                      "cross-entropy from categorical", "negative log-likelihood"],
        key_equations=[r"\hat{\theta} = \arg\max_\theta \sum_i \log p(y_i \mid x_i; \theta)",
                       r"-\log \mathcal{N}(y; \hat{y}, \sigma^2) \propto (y - \hat{y})^2",
                       r"\mathcal{L} = -\sum_i \log p_{\hat{y}_i}"],
        intuition="Loss functions are not arbitrary design choices, they are "
                  "assumptions about noise written as arithmetic. Assume Gaussian "
                  "noise and maximum likelihood hands you squared error. Assume a "
                  "categorical outcome and it hands you cross-entropy. When someone "
                  "asks why we use MSE for regression and cross-entropy for "
                  "classification, this is the answer.",
        shelves=["desk-machine-learning", "desk-mathematics"],
    ),
    Topic(
        id="trees-and-ensembles",
        title="Decision Trees, Random Forests and Boosting",
        level="core",
        prerequisites=["supervised-learning", "bias-variance"],
        key_concepts=["information gain", "Gini impurity", "bagging", "random forest",
                      "gradient boosting", "weak learner", "feature importance"],
        key_equations=[r"G = 1 - \sum_k p_k^2",
                       r"\text{IG} = H(\text{parent}) - \sum_j \tfrac{n_j}{n} H(\text{child}_j)",
                       r"F_{m}(x) = F_{m-1}(x) + \nu\, h_m(x)"],
        intuition="A tree asks a sequence of yes/no questions, each chosen to purify "
                  "the groups most. One tree overfits badly; the fix is to average "
                  "many decorrelated trees (bagging, which attacks variance) or to fit "
                  "each new small tree to the errors of the ensemble so far (boosting, "
                  "which attacks bias). On tabular data boosted trees still routinely "
                  "beat neural networks.",
        shelves=["desk-machine-learning", "desk-data-science"],
    ),
    Topic(
        id="svm-and-kernels",
        title="Support Vector Machines and the Kernel Trick",
        level="core",
        prerequisites=["convexity-and-optimization", "linear-and-logistic-regression"],
        key_concepts=["margin", "support vector", "hinge loss", "kernel trick",
                      "RBF kernel", "dual formulation", "feature map"],
        key_equations=[r"\min_w \tfrac{1}{2}\|w\|^2 \; \text{s.t.}\; y_i(w^\top x_i + b) \ge 1",
                       r"\ell_{\text{hinge}} = \max(0, 1 - y\, f(x))",
                       r"K(x, x') = \phi(x)^\top \phi(x')",
                       r"K_{\text{RBF}}(x,x') = \exp(-\gamma\|x - x'\|^2)"],
        intuition="Do not just separate the classes, separate them with the widest "
                  "possible corridor — that is the margin, and only the points on its "
                  "edge matter. The kernel trick is the elegant part: the whole "
                  "problem depends on the data only through inner products, so you can "
                  "swap in an inner product from an enormous implicit feature space "
                  "and never construct the features at all.",
        shelves=["desk-machine-learning", "desk-mathematics"],
    ),
    Topic(
        id="clustering-and-pca",
        title="Clustering and Dimensionality Reduction",
        level="core",
        prerequisites=["matrix-decompositions", "probability-foundations"],
        key_concepts=["k-means", "centroid", "PCA", "principal component",
                      "explained variance", "t-SNE", "UMAP", "curse of dimensionality"],
        key_equations=[r"\arg\min_S \sum_{k}\sum_{x \in S_k} \|x - \mu_k\|^2",
                       r"C = \tfrac{1}{n}X^\top X, \quad C v_i = \lambda_i v_i",
                       r"\text{explained}_i = \lambda_i / \sum_j \lambda_j"],
        intuition="Unsupervised learning asks what structure the data has before "
                  "anyone labels it. k-means alternates assigning points to the "
                  "nearest centre and moving each centre to its points' mean — it "
                  "always converges, but only to a local optimum, so initialisation "
                  "matters. PCA finds the directions of greatest variance, which are "
                  "the top eigenvectors of the covariance, which are the top singular "
                  "vectors of the centred data.",
        shelves=["desk-machine-learning", "desk-data-science", "desk-mathematics"],
    ),
    Topic(
        id="model-evaluation",
        title="Evaluation, Metrics and Cross-Validation",
        level="core",
        prerequisites=["supervised-learning"],
        key_concepts=["precision", "recall", "F1", "ROC AUC", "confusion matrix",
                      "k-fold cross-validation", "class imbalance", "calibration",
                      "data leakage"],
        key_equations=[r"P = \frac{TP}{TP+FP}, \quad R = \frac{TP}{TP+FN}",
                       r"F_1 = \frac{2PR}{P+R}"],
        intuition="Accuracy is a trap whenever classes are imbalanced — predict the "
                  "majority everywhere and score 99% on a 1% positive rate. Precision "
                  "asks how often your alarms are real, recall asks how many real "
                  "cases you caught, and which you care about is a decision about "
                  "consequences, not statistics. The most damaging evaluation bug is "
                  "not the wrong metric, it is leakage: information from the test set "
                  "reaching the model through preprocessing.",
        shelves=["desk-machine-learning", "desk-data-science"],
    ),

    # ── core: deep learning ───────────────────────────────────────────────
    Topic(
        id="neural-networks-mlp",
        title="Neurons, Layers and the Multilayer Perceptron",
        level="core",
        prerequisites=["linear-and-logistic-regression", "calculus-and-gradients"],
        key_concepts=["perceptron", "MLP", "feedforward", "hidden layer", "universal approximation",
                      "depth versus width", "parameter count", "forward pass"],
        key_equations=[r"h^{(l)} = \sigma\!\left(W^{(l)} h^{(l-1)} + b^{(l)}\right)",
                       r"\hat{y} = W^{(L)}h^{(L-1)} + b^{(L)}"],
        intuition="Stack linear maps with a nonlinearity between them and you can "
                  "approximate any continuous function — that is the universal "
                  "approximation theorem, and it is less useful than it sounds because "
                  "it says nothing about how many neurons or whether you can find the "
                  "weights. Without the nonlinearity the whole stack collapses to a "
                  "single matrix, which is the one-line argument for why activations "
                  "must be nonlinear.",
        shelves=["desk-deep-learning", "desk-machine-learning"],
    ),
    Topic(
        id="backpropagation",
        title="Backpropagation and Automatic Differentiation",
        level="core",
        prerequisites=["neural-networks-mlp", "calculus-and-gradients"],
        key_concepts=["computational graph", "reverse-mode autodiff", "backprop", "chain rule",
                      "vector-Jacobian product", "gradient checking",
                      "vanishing gradient", "exploding gradient"],
        key_equations=[r"\delta^{(L)} = \nabla_{\hat y}\mathcal{L} \odot \sigma'(z^{(L)})",
                       r"\delta^{(l)} = \left(W^{(l+1)\top}\delta^{(l+1)}\right)\odot\sigma'(z^{(l)})",
                       r"\frac{\partial \mathcal{L}}{\partial W^{(l)}} = \delta^{(l)} h^{(l-1)\top}"],
        intuition="Backpropagation is the chain rule with a good order of "
                  "multiplication. A network is a composition of functions, so its "
                  "derivative is a product of Jacobians; multiplying that product "
                  "right-to-left costs one pass instead of one pass per parameter. "
                  "That is the entire trick, and it is why training a billion-parameter "
                  "model costs about twice a forward pass rather than a billion times. "
                  "The vanishing gradient problem is this same product of Jacobians "
                  "shrinking geometrically with depth.",
        shelves=["desk-deep-learning", "desk-mathematics-for-machine-learning-and-deep-learning"],
    ),
    Topic(
        id="activation-functions",
        title="Activation Functions",
        level="core",
        prerequisites=["neural-networks-mlp"],
        key_concepts=["ReLU", "sigmoid", "tanh", "GELU", "SwiGLU", "dying ReLU",
                      "saturation", "gradient flow"],
        key_equations=[r"\mathrm{ReLU}(x) = \max(0, x)",
                       r"\tanh(x) = \frac{e^x - e^{-x}}{e^x + e^{-x}}",
                       r"\mathrm{GELU}(x) = x\,\Phi(x)"],
        intuition="The activation's job is to pass gradient without saturating. "
                  "Sigmoid and tanh flatten at both ends, so deep stacks starve; ReLU "
                  "has derivative exactly 1 on the positive side, which is why it "
                  "unlocked depth. Its cost is the dead-unit failure mode, and the "
                  "smooth modern variants — GELU, SwiGLU — exist to keep the gradient "
                  "flow while softening the kink.",
        shelves=["desk-deep-learning"],
    ),
    Topic(
        id="optimizers",
        title="SGD, Momentum and Adam",
        level="core",
        prerequisites=["gradient-descent", "backpropagation"],
        key_concepts=["momentum", "adaptive learning rate", "Adam", "AdamW",
                      "bias correction", "warmup", "cosine schedule",
                      "gradient clipping"],
        key_equations=[r"v_t = \beta v_{t-1} + (1-\beta)\nabla f,\quad x_{t+1} = x_t - \eta v_t",
                       r"m_t = \beta_1 m_{t-1} + (1-\beta_1) g_t",
                       r"v_t = \beta_2 v_{t-1} + (1-\beta_2) g_t^2",
                       r"x_{t+1} = x_t - \eta \frac{\hat m_t}{\sqrt{\hat v_t} + \epsilon}"],
        intuition="Plain SGD treats every direction alike, which is wrong when the "
                  "loss surface is a long narrow valley. Momentum accumulates velocity "
                  "so consistent directions build speed and oscillations cancel. Adam "
                  "goes further and gives every parameter its own step size, scaled "
                  "down where gradients have been large — which is why it just works "
                  "on badly-scaled problems, and why AdamW's decoupling of weight "
                  "decay from that scaling was a real fix rather than a detail.",
        shelves=["desk-deep-learning", "desk-machine-learning"],
    ),
    Topic(
        id="normalization",
        title="Batch, Layer and RMS Normalisation",
        level="core",
        prerequisites=["neural-networks-mlp", "optimizers"],
        key_concepts=["batch normalisation", "layer normalisation", "RMSNorm",
                      "internal covariate shift", "pre-norm versus post-norm",
                      "training-inference mismatch"],
        key_equations=[r"\hat{x} = \frac{x - \mu}{\sqrt{\sigma^2 + \epsilon}}",
                       r"y = \gamma \hat{x} + \beta",
                       r"\mathrm{RMSNorm}(x) = \frac{x}{\sqrt{\tfrac{1}{n}\sum_i x_i^2}}\,\gamma"],
        intuition="Normalisation keeps activations in a range where gradients behave, "
                  "which lets you use larger learning rates. Batch norm normalises "
                  "across the batch, which couples examples together and breaks down "
                  "for small batches and for sequences — so transformers use layer "
                  "norm, which normalises across features within one example and has "
                  "no train/inference mismatch at all. Putting the norm before the "
                  "sublayer rather than after is what made very deep transformers "
                  "trainable without careful warmup.",
        shelves=["desk-deep-learning", "desk-llms"],
    ),
    Topic(
        id="convolutional-networks",
        title="Convolutional Neural Networks",
        level="core",
        prerequisites=["neural-networks-mlp", "backpropagation"],
        key_concepts=["CNN", "convnet", "convolution", "kernel", "stride", "padding", "pooling",
                      "receptive field", "weight sharing", "translation equivariance",
                      "residual connection"],
        key_equations=[r"(f * g)[n] = \sum_m f[m]\, g[n-m]",
                       r"H_{\text{out}} = \left\lfloor \frac{H + 2p - k}{s} \right\rfloor + 1",
                       r"y = \mathcal{F}(x, \{W_i\}) + x"],
        intuition="A convolution applies the same small filter everywhere, which "
                  "encodes the assumption that a useful pattern is useful wherever it "
                  "occurs. That weight sharing is both a massive parameter saving and "
                  "an inductive bias — translation equivariance — that you get for "
                  "free and cannot easily switch off. Residual connections let the "
                  "gradient reach early layers unattenuated, which is what made "
                  "hundred-layer networks trainable.",
        shelves=["desk-deep-learning", "desk-computer-vision"],
    ),
    Topic(
        id="sequence-models-rnn",
        title="RNNs, LSTMs and the Trouble with Sequences",
        level="core",
        prerequisites=["backpropagation", "activation-functions"],
        key_concepts=["RNN", "recurrent state", "backpropagation through time", "LSTM",
                      "GRU", "gating", "vanishing gradient", "teacher forcing",
                      "sequential bottleneck"],
        key_equations=[r"h_t = \sigma(W_h h_{t-1} + W_x x_t + b)",
                       r"f_t = \sigma(W_f[h_{t-1}, x_t] + b_f)",
                       r"c_t = f_t \odot c_{t-1} + i_t \odot \tilde{c}_t"],
        intuition="A recurrent network carries a state forward, so in principle it "
                  "remembers everything. In practice the gradient through many steps "
                  "is a long product that vanishes or explodes. LSTMs fix it with a "
                  "cell state that is *added* to rather than multiplied through, so "
                  "gradient can flow along an uninterrupted path. What killed RNNs was "
                  "not accuracy but the sequential dependency: you cannot parallelise "
                  "over time, and attention can.",
        shelves=["desk-deep-learning", "desk-nlp"],
    ),
    Topic(
        id="embeddings",
        title="Embeddings and Representation",
        level="core",
        prerequisites=["vectors-and-matrices", "neural-networks-mlp"],
        key_concepts=["word2vec", "distributional hypothesis", "cosine similarity",
                      "embedding space", "contrastive learning", "vector database",
                      "anisotropy"],
        key_equations=[r"\mathrm{sim}(u,v) = \frac{u^\top v}{\|u\|\|v\|}",
                       r"\mathcal{L}_{\text{InfoNCE}} = -\log\frac{e^{s(q,k^+)/\tau}}{\sum_j e^{s(q,k_j)/\tau}}"],
        intuition="An embedding turns a discrete thing into a direction in space so "
                  "that geometry means something: near equals similar. The "
                  "distributional hypothesis is the justification — words in similar "
                  "contexts get similar vectors. Contrastive objectives make this "
                  "explicit by pulling matched pairs together and pushing everything "
                  "else apart, with the temperature controlling how hard the push is.",
        shelves=["desk-nlp", "desk-llms", "desk-deep-learning"],
    ),

    # ── advanced: transformers and language models ────────────────────────
    Topic(
        id="attention-mechanism",
        title="Attention and Scaled Dot-Product",
        level="advanced",
        prerequisites=["embeddings", "neural-networks-mlp", "numerical-stability"],
        key_concepts=["query", "key", "value", "scaled dot-product attention",
                      "softmax", "multi-head attention", "attention mask",
                      "quadratic cost", "KV cache"],
        key_equations=[r"\mathrm{Attention}(Q,K,V) = \mathrm{softmax}\!\left(\frac{QK^\top}{\sqrt{d_k}}\right)V",
                       r"\mathrm{MultiHead}(Q,K,V) = \mathrm{Concat}(\text{head}_1,\dots,\text{head}_h)W^O",
                       r"\mathrm{Var}(q^\top k) = d_k \;\text{for unit-variance components}"],
        intuition="Attention lets every position look at every other and decide, "
                  "per query, what is worth reading. The scaling by √d_k is not "
                  "cosmetic: if query and key components are independent with unit "
                  "variance, their dot product has variance d_k, so for large d_k the "
                  "logits spread out, softmax saturates, and the gradient through it "
                  "collapses. Dividing by √d_k restores unit variance and keeps the "
                  "softmax in its responsive range. Multiple heads exist so different "
                  "subspaces can attend to different relations at once.",
        shelves=["desk-llms", "desk-deep-learning", "desk-nlp", "desk-ai-research-papers"],
    ),
    Topic(
        id="transformer-architecture",
        title="The Transformer Block",
        level="advanced",
        prerequisites=["attention-mechanism", "normalization"],
        key_concepts=["encoder", "decoder", "self-attention", "cross-attention",
                      "feed-forward network", "residual stream", "causal mask",
                      "pre-norm"],
        key_equations=[r"x \leftarrow x + \mathrm{Attn}(\mathrm{LN}(x))",
                       r"x \leftarrow x + \mathrm{FFN}(\mathrm{LN}(x))",
                       r"\mathrm{FFN}(x) = W_2\,\phi(W_1 x + b_1) + b_2"],
        intuition="A transformer block is two operations bolted onto a residual "
                  "stream: attention, which moves information between positions, and "
                  "a position-wise feed-forward network, which does the thinking "
                  "within a position. Reading it as a residual stream that each block "
                  "reads from and writes back to explains a great deal — including why "
                  "the FFN, holding roughly two-thirds of the parameters, is where "
                  "much of the stored knowledge lives.",
        shelves=["desk-llms", "desk-deep-learning", "desk-ai-research-papers"],
    ),
    Topic(
        id="positional-encoding",
        title="Positional Encoding and RoPE",
        level="advanced",
        prerequisites=["attention-mechanism"],
        key_concepts=["sinusoidal encoding", "learned position embedding",
                      "rotary position embedding", "relative position",
                      "context length extrapolation", "ALiBi"],
        key_equations=[r"PE_{(pos, 2i)} = \sin\!\left(pos/10000^{2i/d}\right)",
                       r"PE_{(pos, 2i+1)} = \cos\!\left(pos/10000^{2i/d}\right)",
                       r"\langle R_m q, R_n k\rangle = f(q, k, m-n)"],
        intuition="Attention is permutation-invariant — shuffle the tokens and the "
                  "maths does not notice — so order has to be injected deliberately. "
                  "Sinusoids were the original answer. RoPE is the one that stuck: it "
                  "rotates queries and keys by an angle proportional to position, so "
                  "their inner product depends only on the *difference* in positions. "
                  "Relative position falls out of the algebra rather than being bolted "
                  "on, which is also why RoPE extrapolates better.",
        shelves=["desk-llms", "desk-ai-research-papers"],
    ),
    Topic(
        id="tokenization",
        title="Tokenisation",
        level="advanced",
        prerequisites=["embeddings"],
        key_concepts=["byte-pair encoding", "subword", "vocabulary size",
                      "out-of-vocabulary", "SentencePiece", "token boundary artefacts"],
        key_equations=[r"\text{merge} = \arg\max_{(a,b)} \mathrm{count}(ab)"],
        intuition="Models do not see text, they see integers, and the map between "
                  "them is a compression scheme learned by repeatedly merging the "
                  "commonest adjacent pair. Most of the model's strange failures live "
                  "here: it cannot count letters in a word it sees as one token, "
                  "arithmetic is hard partly because numbers tokenise inconsistently, "
                  "and non-English text costs more tokens for the same content.",
        shelves=["desk-llms", "desk-nlp"],
    ),
    Topic(
        id="pretraining-and-scaling",
        title="Pretraining Objectives and Scaling Laws",
        level="advanced",
        prerequisites=["transformer-architecture", "information-theory"],
        key_concepts=["next-token prediction", "masked language modelling",
                      "scaling laws", "Chinchilla optimal", "compute budget",
                      "emergent capability", "data quality"],
        key_equations=[r"\mathcal{L} = -\sum_t \log p(x_t \mid x_{<t})",
                       r"L(N, D) \approx \frac{A}{N^{\alpha}} + \frac{B}{D^{\beta}} + L_\infty",
                       r"C \approx 6ND"],
        intuition="Predict the next token, over and over, on enough text, and "
                  "something that looks like understanding falls out. Scaling laws say "
                  "loss falls as a power law in parameters and data, which is what "
                  "makes the field's spending decisions forecastable. Chinchilla's "
                  "correction mattered enormously: earlier models were far too large "
                  "for the data they were trained on, and at a fixed compute budget "
                  "you should scale parameters and tokens together.",
        shelves=["desk-llms", "desk-ai-research-papers", "desk-generative-ai"],
    ),
    Topic(
        id="finetuning-and-peft",
        title="Fine-Tuning, LoRA and Parameter-Efficient Adaptation",
        level="advanced",
        prerequisites=["pretraining-and-scaling", "matrix-decompositions"],
        key_concepts=["full fine-tuning", "LoRA", "low-rank adapter", "quantisation",
                      "QLoRA", "catastrophic forgetting", "instruction tuning"],
        key_equations=[r"W' = W_0 + \Delta W, \quad \Delta W = BA",
                       r"B \in \mathbb{R}^{d\times r},\; A \in \mathbb{R}^{r\times k},\; r \ll \min(d,k)"],
        intuition="Full fine-tuning updates every weight and needs optimiser state "
                  "for all of them, which is where the memory goes. LoRA's bet is that "
                  "the *update* a task needs is low-rank even though the weights are "
                  "not — so learn two thin matrices whose product is the change, and "
                  "freeze the rest. You train a fraction of a percent of the "
                  "parameters, and at inference you can fold BA back into W so there "
                  "is no latency cost at all.",
        shelves=["desk-llms", "desk-generative-ai", "desk-ai-research-papers"],
    ),
    Topic(
        id="alignment-and-rlhf",
        title="Instruction Tuning, RLHF and DPO",
        level="advanced",
        prerequisites=["finetuning-and-peft", "policy-gradient"],
        key_concepts=["reward model", "preference data", "PPO", "KL penalty",
                      "direct preference optimisation", "reward hacking",
                      "helpfulness versus harmlessness"],
        key_equations=[r"\max_\pi \mathbb{E}_{y\sim\pi}[r(x,y)] - \beta\, D_{\mathrm{KL}}(\pi \parallel \pi_{\text{ref}})",
                       r"\mathcal{L}_{\text{DPO}} = -\log\sigma\!\left(\beta\log\frac{\pi(y_w|x)}{\pi_{\text{ref}}(y_w|x)} - \beta\log\frac{\pi(y_l|x)}{\pi_{\text{ref}}(y_l|x)}\right)"],
        intuition="A pretrained model predicts likely text, which is not the same as "
                  "being useful or safe. RLHF trains a reward model on human "
                  "preferences and then optimises against it, held near the original "
                  "by a KL penalty — without that leash the policy drifts into "
                  "gibberish that games the reward. DPO's insight is that the optimal "
                  "policy for that objective has a closed form, so you can skip the "
                  "reward model and the RL loop entirely and just fit preferences "
                  "directly.",
        shelves=["desk-llms", "desk-ai-research-papers", "desk-reinforcement-learning"],
    ),
    Topic(
        id="inference-and-decoding",
        title="Decoding, Sampling and Inference Cost",
        level="advanced",
        prerequisites=["pretraining-and-scaling"],
        key_concepts=["greedy decoding", "beam search", "temperature", "top-k",
                      "nucleus sampling", "KV cache", "speculative decoding",
                      "prefill versus decode", "memory bandwidth bound"],
        key_equations=[r"p_i^{(T)} = \frac{e^{z_i/T}}{\sum_j e^{z_j/T}}",
                       r"\text{top-}p:\ \min |S| \ \text{s.t.} \sum_{i\in S} p_i \ge p"],
        intuition="Generation samples one token at a time from a distribution you can "
                  "reshape. Temperature flattens or sharpens it — at T→0 you get "
                  "greedy, at high T you get noise. Nucleus sampling keeps the "
                  "smallest set of tokens covering probability p, which adapts to how "
                  "confident the model is instead of fixing a count. The performance "
                  "story is separate and often surprising: decoding is bound by memory "
                  "bandwidth reading weights, not by arithmetic, which is why batching "
                  "is nearly free and why the KV cache exists.",
        shelves=["desk-llms", "desk-generative-ai"],
    ),
    Topic(
        id="retrieval-augmented-generation",
        title="Retrieval-Augmented Generation",
        level="advanced",
        prerequisites=["embeddings", "inference-and-decoding"],
        key_concepts=["RAG", "chunking", "vector search", "BM25", "hybrid retrieval",
                      "reranking", "context window", "grounding", "citation",
                      "hallucination"],
        key_equations=[r"\mathrm{BM25}(q,d) = \sum_{t\in q} \mathrm{IDF}(t)\cdot\frac{f_{t,d}(k_1+1)}{f_{t,d} + k_1(1-b+b\frac{|d|}{\overline{|d|}})}"],
        intuition="Give the model the right passage and it stops guessing. The hard "
                  "parts are not the generation, they are chunking (too small loses "
                  "context, too large dilutes the match), and the fact that dense "
                  "embeddings and keyword search fail differently — dense finds "
                  "paraphrase, BM25 finds exact rare terms, so hybrid beats either. "
                  "Retrieval quality caps answer quality: no amount of prompting "
                  "rescues a wrong passage.",
        shelves=["desk-llms", "desk-ai", "desk-generative-ai"],
    ),
    Topic(
        id="agents-and-tool-use",
        title="Agents, Tool Use and Orchestration",
        level="advanced",
        prerequisites=["retrieval-augmented-generation"],
        key_concepts=["ReAct", "function calling", "planning", "multi-step reasoning",
                      "tool schema", "reflection", "multi-agent", "error recovery",
                      "context management"],
        key_equations=[],
        intuition="An agent is a model in a loop with the ability to act and observe "
                  "the result. The value is not that the model is smarter but that it "
                  "no longer has to guess at things it can look up or compute — give "
                  "it a calculator and arithmetic stops being a weakness. The failure "
                  "modes are compounding: a wrong step early poisons everything after, "
                  "long loops exhaust context, and without a hard stop an agent will "
                  "cheerfully retry forever.",
        shelves=["desk-ai-agents-and-agentic-ai", "desk-ai", "desk-llms"],
    ),

    # ── advanced: reinforcement learning ──────────────────────────────────
    Topic(
        id="markov-decision-processes",
        title="Markov Decision Processes and Value",
        level="advanced",
        prerequisites=["probability-foundations"],
        key_concepts=["MDP", "state", "action", "reward", "policy", "discount factor",
                      "value function", "Bellman equation", "return"],
        key_equations=[r"G_t = \sum_{k=0}^{\infty} \gamma^k r_{t+k+1}",
                       r"V^\pi(s) = \mathbb{E}_\pi\!\left[r + \gamma V^\pi(s')\mid s\right]",
                       r"Q^*(s,a) = \mathbb{E}\!\left[r + \gamma \max_{a'} Q^*(s',a')\right]"],
        intuition="Reinforcement learning is decision-making when your actions change "
                  "what happens next and the feedback is delayed. The Markov property "
                  "— the future depends on the present state alone — is what makes it "
                  "tractable. The Bellman equation is the whole subject in one line: "
                  "the value of here is the reward now plus the discounted value of "
                  "wherever you land.",
        shelves=["desk-reinforcement-learning", "desk-machine-learning"],
    ),
    Topic(
        id="q-learning",
        title="Q-Learning and Deep Q-Networks",
        level="advanced",
        prerequisites=["markov-decision-processes", "neural-networks-mlp"],
        key_concepts=["temporal difference", "off-policy", "exploration versus exploitation",
                      "epsilon-greedy", "experience replay", "target network",
                      "overestimation bias"],
        key_equations=[r"Q(s,a) \leftarrow Q(s,a) + \alpha\left[r + \gamma\max_{a'}Q(s',a') - Q(s,a)\right]",
                       r"\mathcal{L} = \left(r + \gamma\max_{a'}Q_{\theta^-}(s',a') - Q_\theta(s,a)\right)^2"],
        intuition="Learn the value of each action without ever modelling the "
                  "environment, by bootstrapping: update your estimate toward reward "
                  "plus your own estimate of what comes next. Replacing the table with "
                  "a network breaks the convergence guarantees, and the two hacks that "
                  "made it work — replaying old experience to decorrelate updates, and "
                  "freezing a target network so you are not chasing your own tail — "
                  "are what DQN actually contributed.",
        shelves=["desk-reinforcement-learning", "desk-deep-learning"],
    ),
    Topic(
        id="policy-gradient",
        title="Policy Gradients and Actor-Critic",
        level="advanced",
        prerequisites=["markov-decision-processes", "backpropagation"],
        key_concepts=["REINFORCE", "score function estimator", "baseline",
                      "advantage", "actor-critic", "PPO", "trust region",
                      "variance reduction"],
        key_equations=[r"\nabla_\theta J = \mathbb{E}\!\left[\nabla_\theta \log \pi_\theta(a|s)\, A(s,a)\right]",
                       r"A(s,a) = Q(s,a) - V(s)",
                       r"\mathcal{L}^{\text{PPO}} = \mathbb{E}\left[\min(r_t A_t,\ \mathrm{clip}(r_t, 1-\epsilon, 1+\epsilon)A_t)\right]"],
        intuition="Instead of learning values and acting greedily, adjust the policy "
                  "directly: make actions that did better more likely. The raw "
                  "estimator is unbiased but wildly noisy, so you subtract a baseline "
                  "— giving the advantage, how much better than average this action "
                  "was — which cuts variance without introducing bias. PPO adds a clip "
                  "so a single update cannot move the policy too far, which is the "
                  "practical reason it is the workhorse, including for RLHF.",
        shelves=["desk-reinforcement-learning", "desk-ai-research-papers"],
    ),

    # ── frontier / applied: vision, robotics, systems ─────────────────────
    Topic(
        id="computer-vision-pipeline",
        title="Image Formation, Features and Detection",
        level="frontier",
        prerequisites=["convolutional-networks"],
        key_concepts=["pinhole camera", "intrinsics", "edge detection", "feature matching",
                      "object detection", "IoU", "non-max suppression",
                      "semantic segmentation", "vision transformer"],
        key_equations=[r"s\begin{bmatrix}u\\v\\1\end{bmatrix} = K [R \mid t] \begin{bmatrix}X\\Y\\Z\\1\end{bmatrix}",
                       r"\mathrm{IoU} = \frac{|A \cap B|}{|A \cup B|}"],
        intuition="A camera projects three dimensions onto two and throws depth away; "
                  "everything in vision is an attempt to recover what was lost. "
                  "Classical pipelines hand-designed the features, convolutional nets "
                  "learned them, and vision transformers showed that with enough data "
                  "you can drop the convolutional inductive bias too — cut the image "
                  "into patches and treat them as tokens.",
        shelves=["desk-computer-vision", "desk-deep-learning"],
    ),
    Topic(
        id="robot-kinematics-and-control",
        title="Kinematics, Control and PID",
        level="frontier",
        prerequisites=["vectors-and-matrices", "calculus-and-gradients"],
        key_concepts=["forward kinematics", "inverse kinematics", "degrees of freedom",
                      "homogeneous transform", "Jacobian", "PID control",
                      "feedback loop", "stability"],
        key_equations=[r"T = \begin{bmatrix} R & t \\ 0 & 1\end{bmatrix}",
                       r"\dot{x} = J(q)\,\dot{q}",
                       r"u(t) = K_p e(t) + K_i \int e\,dt + K_d \frac{de}{dt}"],
        intuition="Forward kinematics — where is the hand, given the joint angles — "
                  "is a chain of matrix multiplications and is easy. Inverse "
                  "kinematics is the hard direction and may have many solutions or "
                  "none. Control is the other half: PID is three terms that answer "
                  "how wrong you are now, how long you have been wrong, and how fast "
                  "that is changing, and an astonishing amount of the physical world "
                  "runs on exactly this.",
        shelves=["desk-robotics", "desk-electronics"],
    ),
    Topic(
        id="state-estimation-and-slam",
        title="State Estimation, Kalman Filters and SLAM",
        level="frontier",
        prerequisites=["probability-foundations", "robot-kinematics-and-control"],
        key_concepts=["Kalman filter", "prediction and update", "process noise",
                      "measurement noise", "particle filter", "sensor fusion",
                      "SLAM", "loop closure"],
        key_equations=[r"\hat{x}_{k|k-1} = F\hat{x}_{k-1} + Bu_k",
                       r"K_k = P_{k|k-1}H^\top(HP_{k|k-1}H^\top + R)^{-1}",
                       r"\hat{x}_k = \hat{x}_{k|k-1} + K_k(z_k - H\hat{x}_{k|k-1})"],
        intuition="Every sensor lies a little and every model drifts, so you fuse "
                  "them. The Kalman filter predicts where you should be, measures "
                  "where you seem to be, and splits the difference weighted by which "
                  "it trusts more — the Kalman gain is exactly that trust ratio. It is "
                  "Bayes' rule for Gaussians, and it is optimal when the system really "
                  "is linear with Gaussian noise.",
        shelves=["desk-robotics", "desk-computer-vision", "desk-mathematics"],
    ),
    Topic(
        id="electronics-foundations",
        title="Circuits, Signals and Embedded Systems",
        level="frontier",
        prerequisites=[],
        key_concepts=["Ohm's law", "Kirchhoff's laws", "RC time constant",
                      "operational amplifier", "sampling", "Nyquist rate",
                      "ADC", "PWM", "digital logic"],
        key_equations=[r"V = IR",
                       r"\sum_k I_k = 0,\quad \sum_k V_k = 0",
                       r"\tau = RC",
                       r"f_s > 2 f_{\max}"],
        intuition="Circuits are conservation laws with components attached: charge is "
                  "conserved at every node, energy around every loop. The RC time "
                  "constant is the single most useful number in practical electronics "
                  "— it sets how fast anything can change. Nyquist is the bridge to "
                  "the digital world: sample slower than twice the highest frequency "
                  "and the information is not merely degraded, it is irrecoverably "
                  "aliased into a lie.",
        shelves=["desk-electronics", "desk-robotics"],
    ),
    Topic(
        id="python-for-numerical-work",
        title="Python, NumPy and Vectorised Thinking",
        level="foundations",
        prerequisites=[],
        key_concepts=["ndarray", "broadcasting", "vectorisation", "views versus copies",
                      "dtype", "in-place operations", "profiling", "memory layout"],
        key_equations=[],
        intuition="NumPy is fast because the loop happens in C, so the skill is "
                  "expressing computation as whole-array operations rather than "
                  "Python loops. Broadcasting is the rule that lets arrays of "
                  "different shapes combine without copying, and it is the source of "
                  "both great elegance and the most baffling bugs — a stray shape of "
                  "(n,1) versus (n,) silently produces an n×n matrix instead of an "
                  "error.",
        shelves=["desk-python", "desk-computer-science", "desk-data-science"],
    ),
    Topic(
        id="generative-models",
        title="Generative Models: VAEs, GANs and Diffusion",
        level="frontier",
        prerequisites=["maximum-likelihood", "information-theory", "backpropagation"],
        key_concepts=["latent variable", "VAE", "variational autoencoder", "ELBO",
                      "reparameterisation trick", "GAN", "adversarial training",
                      "mode collapse", "diffusion", "denoising", "score matching"],
        key_equations=[r"\mathcal{L}_{\text{ELBO}} = \mathbb{E}_{q}[\log p(x|z)] - D_{\mathrm{KL}}(q(z|x)\parallel p(z))",
                       r"\min_G \max_D \mathbb{E}_x[\log D(x)] + \mathbb{E}_z[\log(1 - D(G(z)))]",
                       r"x_t = \sqrt{\bar\alpha_t}\,x_0 + \sqrt{1-\bar\alpha_t}\,\epsilon"],
        intuition="All three learn to produce samples, by different bargains. A VAE "
                  "maximises a tractable lower bound on likelihood and gets blurry but "
                  "stable results. A GAN sets two networks against each other and gets "
                  "sharpness at the cost of a training process that can collapse. "
                  "Diffusion destroys data with noise in small steps and learns to "
                  "undo one step at a time — a much easier task than generating in one "
                  "leap, which is why it won.",
        shelves=["desk-generative-ai", "desk-deep-learning", "desk-ai-research-papers"],
    ),
    Topic(
        id="evaluation-of-llms",
        title="Evaluating Language Models",
        level="frontier",
        prerequisites=["pretraining-and-scaling", "model-evaluation"],
        key_concepts=["benchmark", "perplexity", "contamination", "LLM-as-judge",
                      "human evaluation", "pass@k", "calibration", "eval overfitting"],
        key_equations=[r"\text{pass@}k = \mathbb{E}\left[1 - \frac{\binom{n-c}{k}}{\binom{n}{k}}\right]"],
        intuition="Evaluating a general system is much harder than evaluating a "
                  "classifier, because there is no single right answer. Benchmarks "
                  "leak into training data and stop measuring anything; using a model "
                  "as judge is cheap and correlates decently with humans but inherits "
                  "the judge's biases, including a preference for verbose answers that "
                  "look like its own. Treat any single headline number with suspicion.",
        shelves=["desk-llms", "desk-ai-research-papers", "desk-machine-learning"],
    ),
    Topic(
        id="mlops-and-production",
        title="Deploying and Operating ML Systems",
        level="frontier",
        prerequisites=["model-evaluation", "python-for-numerical-work"],
        key_concepts=["training-serving skew", "data drift", "concept drift",
                      "monitoring", "feature store", "reproducibility", "versioning",
                      "shadow deployment", "rollback"],
        key_equations=[],
        intuition="A model in production is a system, not an artefact. The failures "
                  "are rarely the mathematics: they are the same preprocessing written "
                  "twice and drifting apart, the input distribution changing while the "
                  "model stays fixed, and nobody noticing because accuracy is not "
                  "measurable without labels. Monitor the inputs, not just the "
                  "outputs — drift shows up there first.",
        shelves=["desk-data-science", "desk-computer-science", "desk-machine-learning"],
    ),
]}


# ── matching: which topics does this question touch? ──────────────────────
# Ported from the Quantum Professor, where bare token overlap let a ubiquitous
# word decide the match. IDF weighting makes a rare, specific term outweigh a
# common one, which is what you want when "model" and "learning" appear in
# half the curriculum.

_STOP = set("the a an of for on in is are do does can could would should will "
            "me my you your i we us what how why with about and or but so to "
            "that this it its at be by as from into than then there".split())


def _stem(w: str) -> str:
    """Fold plural and verb endings so both sides agree on a word.

    Only consistency matters, not linguistic correctness — question and
    curriculum run through the same fold. Without the -ing/-ed arm, "scale"
    in a question matched neither "scaled dot-product" nor "scaling laws",
    so the most informative word in the question scored zero.
    """
    for suf in ("ing", "ed", "s"):
        if len(w) > len(suf) + 3 and w.endswith(suf):
            if suf == "s" and w.endswith(("ss", "us", "is", "as")):
                continue
            return w[:-len(suf)]
    return w


def _tokens(text: str) -> set:
    return {_stem(w) for w in re.findall(r"[a-z][a-z-]{2,}", text.lower())
            if w not in _STOP}


# Structural LaTeX, not mathematics. Stripping backslashes turns every command
# into a bare word, so "\cup" in the IoU formula became the token "cup" and
# "who won the world cup" matched the computer-vision topic. Commands that do
# carry meaning — sqrt, log, exp, sum, max — are deliberately not listed.
_LATEX_NOISE = set("""
frac dfrac tfrac mathrm mathbb mathcal boldsymbol bm text texttt rm
left right big bigg begin end quad qquad cdot cdots ldots dots
bmatrix pmatrix vmatrix matrix array align cases
cup cap subset supset setminus emptyset
top bot mid parallel langle rangle lfloor rfloor lceil rceil
hat bar tilde vec dot ddot overline underline
alpha beta gamma delta epsilon varepsilon zeta eta theta vartheta iota
kappa lambda mu nu xi omicron rho sigma tau upsilon phi varphi chi psi omega
Gamma Delta Theta Lambda Sigma Phi Psi Omega
approx neq leq geq ll gg propto sim simeq equiv
partial infty forall exists in notin
odot otimes oplus times div pm mp
operatorname displaystyle limits nolimits
""".split())


def _equation_tokens(eqs: List[str]) -> set:
    r"""Meaningful identifiers inside LaTeX, so a quoted formula matches.

    "why divide by sqrt(d_k)" should land on attention, whose equation says
    \sqrt{d_k} — but equations were excluded from matching entirely, so the
    single most specific term in such a question contributed nothing.
    """
    words = re.findall(r"[a-zA-Z][a-zA-Z_]{2,}", " ".join(eqs).replace("\\", " "))
    out = set()
    for w in words:
        low = w.lower()
        if low in _LATEX_NOISE:
            continue
        out.add(_stem(low))
        # d_k and \bar\alpha_t also carry their stem: d, alpha
        for part in low.split("_"):
            if len(part) > 2 and part not in _LATEX_NOISE:
                out.add(_stem(part))
    return out - _STOP


def _topic_fields(t: Topic):
    """(strong, weak). Title/id/concepts/equations name the subject; the
    intuition paragraph merely mentions things in passing."""
    strong = _tokens(" ".join([t.title, t.id.replace("-", " "),
                               " ".join(t.key_concepts)]))
    strong |= _equation_tokens(t.key_equations)
    return strong, _tokens(t.intuition) - strong


_DF: Dict[str, int] = {}
for _t in TOPICS.values():
    _s, _w = _topic_fields(_t)
    for _tok in (_s | _w):
        _DF[_tok] = _DF.get(_tok, 0) + 1
_NTOPICS = max(len(TOPICS), 1)


def _idf(tok: str) -> float:
    return math.log(1.0 + _NTOPICS / (1 + _DF.get(tok, 0)))


def match_topics(question: str, k: int = 4) -> List[Topic]:
    """The k curriculum topics a question most plausibly touches."""
    q = _tokens(question)
    if not q:
        return []
    scored = []
    for t in TOPICS.values():
        strong, weak = _topic_fields(t)
        # Prose hits are worth far less than subject hits, and their total is
        # capped. At the old 2:1 ratio two incidental words in an intuition
        # paragraph ("over", "scale") outscored the actual subject word in a
        # title, and a question about attention matched Scaling Laws.
        strong_score = sum(_idf(w) for w in q & strong) * 3.0
        weak_score = min(sum(_idf(w) for w in q & weak) * 0.4, 2.0)
        score = strong_score + weak_score
        if t.title.lower() in question.lower():
            score += 10.0                    # the question names the topic outright
        # A topic matched only on prose is not matched. "What is the best pizza
        # in Naples" scored 1.28 against Eigendecomposition because "best"
        # appears in its intuition paragraph — enough to clear a bare
        # score-above-zero test and hand the professor an absurd source.
        if strong_score > 0:
            scored.append((score, t))
    scored.sort(key=lambda p: (-p[0], p[1].title))
    # Returning junk is worse than returning nothing: the professor would try
    # to build on an unrelated topic and the validator would have to police it.
    if not scored or scored[0][0] < 2.5:
        return []
    return [t for _s, t in scored[:k]]


def curriculum_block(topics: List[Topic]) -> str:
    """Render topics as citable sources, in the same shape as book passages."""
    if not topics:
        return ""
    return "\n\n".join(
        f"[C:{t.id}] {t.title} ({t.level})\n"
        f"  intuition: {t.intuition}\n"
        f"  key concepts: {', '.join(t.key_concepts)}"
        + (f"\n  key equations (LaTeX): {' ; '.join(t.key_equations)}"
           if t.key_equations else "")
        for t in topics)


def topics_at_level(level: str) -> List[Topic]:
    return [t for t in TOPICS.values() if t.level == level]


def prerequisite_gaps(topics: List[Topic]) -> List[Topic]:
    """Direct prerequisites of the given topics that aren't already covered.

    Milestone 4: the prerequisite graph on Topic.prerequisites has existed
    since this module was written but was never read by anything — every
    topic's dependencies were real data with no consumer. One level, not the
    full transitive closure via learning_path() below: a reader missing a
    topic's direct prerequisite needs a pointer to that one thing, not an
    entire multi-step curriculum unrolled into their answer. Deduplicated,
    in the order first encountered."""
    covered = {t.id for t in topics}
    seen: set = set()
    gaps: List[Topic] = []
    for t in topics:
        for pid in t.prerequisites:
            if pid in covered or pid in seen or pid not in TOPICS:
                continue
            seen.add(pid)
            gaps.append(TOPICS[pid])
    return gaps


def learning_path(topic_id: str) -> List[str]:
    """Prerequisites first, depth-first, each topic once."""
    seen, order = set(), []

    def walk(tid: str) -> None:
        if tid in seen or tid not in TOPICS:
            return
        seen.add(tid)
        for p in TOPICS[tid].prerequisites:
            walk(p)
        order.append(tid)

    walk(topic_id)
    return order


def concept_progression(topics: List[Topic], cap: int = 10) -> List[Topic]:
    """The mental progression a "teach me X" question should walk through,
    foundations first — e.g. for attention-mechanism: vectors-and-matrices,
    neural-networks-mlp, embeddings, numerical-stability, attention-mechanism.

    learning_path() already does the depth-first prerequisite walk for ONE
    topic; this merges that walk across every matched topic (a question can
    touch more than one), dedupes, and caps the length so a deep topic like
    alignment-and-rlhf (six-plus levels down) doesn't hand the teaching stage
    a 15-step wall nobody asked for — the cap keeps the LAST `cap` steps
    (closest to what was actually asked), not the first, since dropping the
    beginning of a long chain loses less than dropping the end the reader
    actually asked about.

    Returns plain Topics with no notion of what the reader already knows —
    that's mastery.known_topic_ids(), a separate concern this module stays
    free of (see recommend_next()'s docstring for why). The caller marks
    already-known steps itself; pipeline.professor_engine does this by
    checking each returned topic's id against known_ids it was passed
    separately, rather than this function trying to bake that in."""
    seen: set = set()
    order: List[Topic] = []
    for t in topics:
        for tid in learning_path(t.id):
            if tid in seen or tid not in TOPICS:
                continue
            seen.add(tid)
            order.append(TOPICS[tid])
    if len(order) > cap:
        order = order[-cap:]
    return order


def recommend_next(known_ids: "set[str]", exposed_ids: "set[str]",
                   recent_ids: "list[str]" = (), n: int = 5) -> List[Topic]:
    """What to study next, from real prerequisite gaps — not a generic
    "here are some popular topics" list.

    Takes plain id sets rather than importing mastery.py directly (same
    reason concept_progression() takes `known` as a parameter instead of
    importing it): this module stays free of the sqlite/mastery dependency,
    and is trivially testable with hand-built sets instead of a real
    database.

    known_ids   — mastery.known_topic_ids(): manually marked known, or
                  engaged with directly often enough to count as known.
    exposed_ids — every topic_id that has ever appeared in a real answer
                  (mastery_summary()'s topic_id column), known or not —
                  used to avoid re-recommending something already surfaced,
                  even if the reader hasn't engaged with it enough to be
                  "known" yet.
    recent_ids  — most-recently-studied topic_ids, most recent first
                  (mastery.recently_studied()) — used to prefer a topic that
                  actually connects to what was just learned over an
                  unrelated one that also happens to be ready.

    A topic is "ready" when every one of its prerequisites is in known_ids —
    the reader has the foundation for it, whether or not they've seen it yet.
    Among ready, unexposed topics, ones sharing key_concepts with a recently
    studied topic rank first (the concrete next step from where the reader
    actually is), then earlier curriculum levels, then title for a stable
    order. If nothing is fully ready (early in the curriculum, most
    prerequisite chains still open), falls back to the topics with the
    fewest missing prerequisites — the closest thing to "ready" available —
    so this never returns an empty list just because the reader is new."""
    candidates = [t for t in TOPICS.values() if t.id not in exposed_ids]
    if not candidates:
        return []

    def missing_prereqs(t: Topic) -> int:
        return sum(1 for p in t.prerequisites if p not in known_ids)

    ready = [t for t in candidates if missing_prereqs(t) == 0]
    pool = ready if ready else candidates
    level_rank = {lv: i for i, lv in enumerate(LEVELS)}

    recent_concepts: set = set()
    for rid in list(recent_ids)[:3]:
        rt = TOPICS.get(rid)
        if rt:
            recent_concepts |= {c.lower() for c in rt.key_concepts}

    def sort_key(t: Topic):
        overlap = len(recent_concepts & {c.lower() for c in t.key_concepts})
        return (missing_prereqs(t), -overlap, level_rank.get(t.level, 9), t.title)

    pool.sort(key=sort_key)
    return pool[:n]


def related_topics(topic: Topic, k: int = 4) -> List[Topic]:
    """Other topics that share the most key_concepts with this one — a cheap,
    always-current stand-in for a hand-authored "related/contrasts/
    applications" graph edge, which would mean manually curating relationships
    for 40+ topics and keeping them in sync by hand every time a topic is
    added. Concept overlap is a reasonable proxy: topics sharing several
    named concepts are topics a reader moving through one would plausibly
    want pointed at next, whether that's a contrast, an application, or an
    extension — the professor prompt is what decides which relationship it
    actually is when it uses these, not this function."""
    mine = {c.lower() for c in topic.key_concepts}
    scored = []
    for other in TOPICS.values():
        if other.id == topic.id:
            continue
        theirs = {c.lower() for c in other.key_concepts}
        overlap = len(mine & theirs)
        if overlap:
            scored.append((overlap, other))
    scored.sort(key=lambda p: (-p[0], p[1].title))
    return [t for _n, t in scored[:k]]


if __name__ == "__main__":
    import json
    import sys
    if len(sys.argv) > 1:
        for t in match_topics(" ".join(sys.argv[1:])):
            print(f"  {t.id:38s} {t.level:12s} {t.title}")
    else:
        by_level = {lv: len(topics_at_level(lv)) for lv in LEVELS}
        print(json.dumps({"topics": len(TOPICS), "by_level": by_level}, indent=1))
