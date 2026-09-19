export function text<K extends keyof HTMLElementTagNameMap>(
  tag: K,
  value: string,
): HTMLElementTagNameMap[K] {
  const element = document.createElement(tag);
  element.textContent = value;
  return element;
}
