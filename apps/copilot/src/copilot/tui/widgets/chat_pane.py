from textual.widgets import Static
from textual.reactive import reactive

class ChatPane(Static):

    messages = reactive([])

    def __init__(self, app):
        super().__init__()
        self.messages = app.messages

    def watch_messages(self, messages):
          self.update(
               "\n\n".join(
                    f"{m.role}: {m.content}" 
                    for m in messages
               )
          )