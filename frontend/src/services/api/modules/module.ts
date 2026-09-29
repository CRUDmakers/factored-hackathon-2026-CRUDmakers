export default abstract class ApiModule {
    protected baseUrl: string;

    constructor(baseUrl: string) {
        this.baseUrl = baseUrl;
    }

    protected async post<TResponse>(endpoint: string, body: any, params?: URLSearchParams): Promise<TResponse> {
        const res = await fetch(this._resolveUrlWithParams(endpoint, params), {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(body),
        });

        if (!res.ok) throw new Error(`Failed to post ${endpoint}: ${res.statusText}`);

        return await res.json();
    }

    private _resolveUrlWithParams(endpoint: string, params?: URLSearchParams): string {
        if (!params) return this._resolveUrl(endpoint);
        return `${this._resolveUrl(endpoint)}?${params.toString()}`;
    }

    private _resolveUrl(endpoint: string): string {
        return `${this.baseUrl}${endpoint}`;
    }
}
