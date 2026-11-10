# tek-runtime

Kaggle-side QEMU session manager for TEK (Temporary Environment on Kaggle).

## Installation (from the TEK repo)

```bash
pip install "git+https://github.com/ALI88708/TEK.git#subdirectory=packages/tek-runtime"
```

## Usage in a Kaggle notebook

```python
from tek_runtime import main
main()   # TEK_SESSION_SECRET must be set as a Kaggle secret
```
