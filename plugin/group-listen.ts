import type { Account, Chat } from "./transport.ts";

/**
 * A group text on the phone line: the agent listens there and never speaks.
 * It classifies each message in silence and records priority signals; replies,
 * typing and failure notices never reach the chat. One definition, shared by
 * the turn (receive) and the transport's failure notice.
 */
export function isListeningGroup(account: Pick<Account, "accountId">, chat: Pick<Chat, "participants">): boolean {
  return account.accountId === "chat" && chat.participants.length > 2;
}
