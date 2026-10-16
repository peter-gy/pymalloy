import type { HostAnswers, Request } from "@pymalloy/protocol";
import { CompilerSession } from "./session";

const compiler = new CompilerSession();

Object.defineProperty(globalThis, "__pymalloy", {
  value: Object.freeze({
    start(requestJSON: string): string {
      const request: Request = JSON.parse(requestJSON);
      return JSON.stringify(compiler.start(request));
    },
    step(answersJSON: string): string {
      const answers: HostAnswers = JSON.parse(answersJSON);
      return JSON.stringify(compiler.step(answers));
    },
    close(): void {
      compiler.close();
    },
  }),
});
