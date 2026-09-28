
<h1 align="center">
  <a href="https://dbgpt.site"><img width="96" src="https://github.com/eosphoros-ai/DB-GPT-Web/assets/10321453/062ee3ea-fac2-4437-a392-f4bc5451d116" alt="DB-GPT"></a>
  <br>
  DB-GPT-Web
</h1>

_<p align="center">DB-GPT Chat UI, LLM to Vision.</p>_

<p align="center">
  <a href="https://github.com/eosphoros-ai/DB-GPT-Web/blob/main/LICENSE">
    <img src="https://img.shields.io/badge/license-MIT-blue.svg?label=License&style=flat" />
  </a>
  <a href="https://github.com/eosphoros-ai/DB-GPT/releases">
    <img alt="Release Notes" src="https://img.shields.io/github/release/eosphoros-ai/DB-GPT" />
  </a>
  <a href="https://github.com/eosphoros-ai/DB-GPT-Web/issues">
    <img alt="Open Issues" src="https://img.shields.io/github/issues-raw/eosphoros-ai/DB-GPT-Web" />
  </a>
  <a href="https://discord.gg/7uQnPuveTY">
    <img alt="Discord" src="https://dcbadge.vercel.app/api/server/7uQnPuveTY?compact=true&style=flat" />
  </a>
</p>

---

## 👋 Introduction

***DB-GPT-Web*** is an **Open source chat UI** for [**DB-GPT**](https://github.com/eosphoros-ai/DB-GPT).
Also, it is a **LLM to Vision** solution. 

[DB-GPT-Web](https://dbgpt.site) is an Open source Tailwind and Next.js based chat UI for AI and GPT projects. It beautify a lot of markdown labels, such as `table`, `thead`, `th`, `td`, `code`, `h1`, `h2`, `ul`, `li`, `a`, `img`. Also it define some custom labels to adapted to AI-specific scenarios. Such as `plugin running`, `knowledge name`, `Chart view`, and so on.

## 💪🏻 Getting Started

### Prerequisites

- [Node.js](https://nodejs.org/) >= 16
- [npm](https://npmjs.com/) >= 8
- [yarn](https://yarnpkg.com/) >= 1.22
- Supported OSes: Linux, macOS and Windows

### Installation

Using **Yarn** is recommended for dependency management.

```sh
# Install dependencies
npm install
yarn install
```

### Usage
```sh
cp .env.template .env
```
For same-origin deployments, leave `API_BASE_URL` empty. The Next.js server proxies `/api/v1` and `/api/v2` to `API_PROXY_TARGET` (default `http://127.0.0.1:5670`). The streaming Agent request uses `/api/agent-stream`, which forwards SSE chunks and aborts its upstream request when the browser disconnects; set `API_PROXY_TARGET` for both the Next.js build and runtime when DB-GPT listens elsewhere. Set `API_BASE_URL` only when the browser must call an external API origin directly.

```sh
# development model
npm run dev
yarn dev
```

## 🚀 Use In DB-GPT

```sh
bash ../scripts/build_web_static.sh
```

## 📚 Documentation

For full documentation, visit [document](https://docs.dbgpt.site/).


## Usage
  [gpt-vis](https://github.com/eosphoros-ai/DB-GPT/gpt-vis) for markdown support.
  [ant-design](https://github.com/ant-design/ant-design) for ui components.
  [next.js](https://github.com/vercel/next.js) for server side rendering.
  [@antv/g2](https://github.com/antvis/g2#readme) for charts.

## License

DB-GPT-Web is licensed under the [MIT License](LICENSE).

---

Enjoy using DB-GPT-Web to build stunning UIs for your AI and GPT projects.

🌟 If you find it helpful, don't forget to give it a star on GitHub! Stars are like little virtual hugs that keep us going! We appreciate every single one we receive.

For any queries or issues, feel free to open an [issue](https://github.com/eosphoros-ai/DB-GPT-Web/issues) on the repository.

Happy coding! 😊


## antdbgptweb installation

### deploy in local environment:
