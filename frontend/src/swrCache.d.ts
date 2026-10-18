export declare function peek<T>(key: string): T | undefined;
export declare function cached<T>(key: string, loader: () => Promise<T>, maxAgeMs?: number): Promise<T>;
export declare function invalidate(prefix: string): void;
