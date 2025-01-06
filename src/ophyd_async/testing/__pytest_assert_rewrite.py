import pytest

# So that bare asserts give a nice pytest traceback
pytest.register_assert_rewrite("ophyd_async.testing._assert")
