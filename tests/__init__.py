
# テストが、画面から保存した本物のキーで API を呼ばないように、読む先を外す。
import os as _os
import tempfile as _tempfile

from app import claude as _claude

_claude.KEY_FILE = _os.path.join(_tempfile.gettempdir(), "shinsui-tests-no-such-key", ".anthropic_api_key")
# テストの応答をキャッシュに残さない。キャッシュのテストだけが明示して使う。
_os.environ["ANTHROPIC_NO_CACHE"] = "1"
