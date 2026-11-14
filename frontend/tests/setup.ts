import { Window } from "happy-dom"

const window = new Window({ url: "http://localhost:3000" })
for (const name of ["window", "document", "navigator", "HTMLElement", "HTMLInputElement", "Element", "Node", "DocumentFragment", "MutationObserver", "Event", "MouseEvent", "KeyboardEvent"]) {
  const value = name === "window" ? window : Reflect.get(window, name)
  Object.defineProperty(globalThis, name, { value, configurable: true, writable: true })
}
Object.defineProperty(globalThis, "IS_REACT_ACT_ENVIRONMENT", { value: true, configurable: true, writable: true })
