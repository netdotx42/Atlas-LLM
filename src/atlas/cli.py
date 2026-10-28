import uvicorn


def main() -> None:
    uvicorn.run("atlas.api.app:app", host="127.0.0.1", port=8000, factory=False)


if __name__ == "__main__":
    main()
