import sys

import uvicorn

from atlas.config import Settings
from atlas.model.runtime import pull_model


def main() -> None:
    if len(sys.argv) > 1 and sys.argv[1] == "pull-model":
        path = pull_model(Settings())
        print(path)
        return
    uvicorn.run("atlas.api.app:app", host="127.0.0.1", port=8000, factory=False)


if __name__ == "__main__":
    main()
