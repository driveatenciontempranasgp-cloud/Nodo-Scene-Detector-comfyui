# Lo usa ComfyUI-Manager; la instalación real está en __init__.py
import importlib.util, os, sys
sys.path.insert(0, os.path.dirname(__file__))
spec = importlib.util.spec_from_file_location("dt_init", os.path.join(os.path.dirname(__file__), "__init__.py"))
m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
