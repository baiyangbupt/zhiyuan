declare module 'marked' {
  export interface Marked {
    (src: string): string;
    parse(src: string): string;
    use(options: Record<string, unknown>): Marked;
    setOptions(options: Record<string, unknown>): Marked;
  }

  const marked: Marked;
  export { marked };
  export default marked;
}
