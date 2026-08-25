import { CLIENT_SDK_ERRORS } from "../../contracts/src/index.ts";
import { ClientRuntimeError } from "./errors.ts";

export type ClientActionHandler = (
  args: Record<string, unknown>,
) => Promise<Record<string, unknown>> | Record<string, unknown>;

/** Registry of mounted action handlers; duplicates conflict. */
export class MountedActionRegistry {
  private handlers = new Map<string, ClientActionHandler>();

  mount(name: string, handler: ClientActionHandler): void {
    if (this.handlers.has(name)) {
      throw new ClientRuntimeError(
        "action_already_mounted",
        `action ${name} is already mounted`,
      );
    }
    this.handlers.set(name, handler);
  }

  unmount(name: string): void {
    this.handlers.delete(name);
  }

  names(): string[] {
    return [...this.handlers.keys()];
  }

  has(name: string): boolean {
    return this.handlers.has(name);
  }

  async dispatch(
    name: string,
    args: Record<string, unknown>,
  ): Promise<Record<string, unknown>> {
    const handler = this.handlers.get(name);
    if (handler === undefined) {
      throw new ClientRuntimeError(
        CLIENT_SDK_ERRORS.ACTION_NOT_MOUNTED,
        `action ${name} is not mounted on this page`,
      );
    }
    return handler(args);
  }
}
