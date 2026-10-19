// The Book's Pi has one tool: call this plugin's engine directly, never a shell.
// No player extensions, MCP servers, file tools or campaign-local code are loaded.
import { spawn } from "node:child_process";
import { fileURLToPath } from "node:url";

const solo = fileURLToPath(new URL("../bin/solo", import.meta.url));
const outputLimit = 50000;

export default function (pi) {
  const allowed = new Set(JSON.parse(process.env.SOLO_GM_COMMANDS || "[]"));
  pi.registerTool({
    name: "solo",
    label: "Campaign engine",
    description: 'Run a solo campaign command. Supply arguments as separate strings, without "solo", shell quoting, pipes or redirects. Example: {"args":["rule","travel"]}. For a commit, pass JSON as one argument, or use {"args":["commit","-"],"input":"{...}"}.',
    parameters: {
      type: "object",
      properties: {
        args: { type: "array", items: { type: "string", maxLength: 100000 }, minItems: 1, maxItems: 128 },
        input: { type: "string", maxLength: 100000 },
      },
      required: ["args"],
      additionalProperties: false,
    },
    async execute(_id, { args, input = "" }, signal, _update, ctx) {
      if (!process.env.SOLO_GM || !allowed.has(args[0])) {
        throw new Error("Only the GM's campaign commands are available; setup, settings, other campaigns and agents are not.");
      }
      if (args.some(arg => arg.startsWith("-C") || arg.startsWith("--campaign")
          || (arg.startsWith("--c") && "--campaign".startsWith(arg)))) {
        throw new Error("The GM cannot select another campaign.");
      }
      return await new Promise((resolve, reject) => {
        const child = spawn(solo, args, { cwd: ctx.cwd, env: process.env, signal, timeout: 30000, shell: false });
        let output = "", truncated = false;
        const collect = data => {
          const text = data.toString();
          truncated ||= output.length + text.length > outputLimit;
          output = (output + text).slice(0, outputLimit);
        };
        child.stdout.setEncoding("utf8");
        child.stderr.setEncoding("utf8");
        child.stdout.on("data", collect);
        child.stderr.on("data", collect);
        child.on("error", reject);
        child.on("close", code => resolve({
          content: [{ type: "text", text: (output || "No output.") + (truncated ? "\n[output truncated; ask for fewer entries]" : "") }],
          details: { exitCode: code },
          isError: code !== 0,
        }));
        child.stdin.on("error", () => {}); // an early exit can close stdin before a large commit is written
        child.stdin.end(input);
      });
    },
  });
}
