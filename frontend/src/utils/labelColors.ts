export function getLabelColorClass(label: string, labels: string[]): string {
  const index = labels.indexOf(label);
  if (index === -1) return "label1";
  return `label${(index % 9) + 1}`;
}
