from textual.message import Message

class UserInputSubmitted(Message):
    def __init__(self, text: str) -> None:
        super().__init__()
        self.text = text