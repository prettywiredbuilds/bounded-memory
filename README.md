# Bounded Memory

A Python agent built with the Anthropic SDK that maintains persistent, token-bounded conversation memory across sessions. The agent stores messages in Azure DocumentDB, trims the active history to a fixed token budget, and folds dropped messages into a rolling summary that is re-injected into the system prompt on every turn.

![Architecture diagram showing Scout's bounded-memory flow: session resumption reads from MongoDB, the rolling summary is injected into the system prompt, incoming user messages are token-counted and appended to the working window, the window is trimmed exchange-by-exchange to stay within the token budget, dropped exchanges are incrementally summarized and merged back into the stored summary, and both the updated session state and raw message logs are written to separate MongoDB collections.](bounded-memory-flow.png)

## Prerequisites

- Python 3.8+
- [Visual Studio Code](https://code.visualstudio.com/)
- [DocumentDB for VS Code](https://marketplace.visualstudio.com/items?itemName=ms-azuretools.vscode-documentdb) extension
- An [Anthropic API key](https://console.anthropic.com/)
- An [Azure DocumentDB](https://azure.microsoft.com/products/documentdb) resource
- The `anthropic` and `pymongo` Python packages

Install the required packages:

```bash
pip install anthropic pymongo
```

Set your Anthropic API key as an environment variable:

```bash
export ANTHROPIC_API_KEY="your-api-key-here"
```

Copy `.env.example` to `.env` and insert your Azure DocumentDB connection string:

```bash
cp .env.example .env
```

Then open `.env` and replace the placeholder with your connection string:

```
CONNECTION_STRING="your-documentdb-connection-string-here"
```

## Setup

Run the database setup script once to create the required MongoDB indexes:

```bash
python setup.py
```

## View the Database

Use the DocumentDB extension in VS Code to inspect your data. Once connected with your connection string, you can browse the database, collections, and individual documents directly from the VS Code sidebar.

## Run the Sample

```bash
python main.py
```

Once running, type a message and press Enter to get a response. The agent resumes the previous session on each restart. Type `quit` to exit.

Each response includes a token usage summary showing the number of input and output tokens consumed for that turn. Because the agent sends only a rolling summary plus a small recency window — rather than the full conversation history — input token counts stay low and predictable regardless of how long the conversation grows. This bounded approach can significantly reduce API costs compared to naively resending the entire transcript on every turn.

## Issues & Questions

If you run into any problems or have questions, please [file an issue](../../issues).
