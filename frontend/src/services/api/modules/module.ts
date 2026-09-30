export default abstract class ApiModule {
    protected baseUrl: string;

    constructor(baseUrl: string) {
        this.baseUrl = baseUrl;
    }

    protected async post<TResponse>(endpoint: string, body?: any, params?: URLSearchParams): Promise<TResponse> {
        const res = await fetch(this._resolveUrlWithParams(endpoint, params), {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: body ? JSON.stringify(body) : undefined,
        });

        if (!res.ok) throw new Error(`Failed to post ${endpoint}: ${res.statusText}`);

        return await res.json();
    }

    protected async get<TResponse>(endpoint: string, params?: URLSearchParams): Promise<TResponse> {
        const res = await fetch(this._resolveUrlWithParams(endpoint, params), {
            method: "GET",
            headers: { "Content-Type": "application/json" },
        });

        if (!res.ok) throw new Error(`Failed to get ${endpoint}: ${res.statusText}`);

        return await res.json();
    }

    protected async sleep(ms: number): Promise<void> {
        return new Promise((resolve) => setTimeout(resolve, ms));
    }

    private _resolveUrlWithParams(endpoint: string, params?: URLSearchParams): string {
        if (!params) return this._resolveUrl(endpoint);
        return `${this._resolveUrl(endpoint)}?${params.toString()}`;
    }

    private _resolveUrl(endpoint: string): string {
        return `${this.baseUrl}${endpoint}`;
    }
}
