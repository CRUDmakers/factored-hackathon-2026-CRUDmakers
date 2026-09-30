import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Progress } from "@/components/ui/progress";
import { ArrowRight, ArrowUpRight, CreditCard, HandCoins, Landmark, Plus, ShieldCheck } from "lucide-react";

export default function HomePage() {
    const accounts: { id: string; type: string; name: string }[] = [
        { id: "1", type: "Conta corrente", name: "Conta principal" },
    ];

    return (
        <div className="bg-background flex h-svh w-svw flex-row">
            <aside className="bg-sidebar flex h-full w-sm"></aside>

            <main className="flex size-full flex-col gap-6 overflow-auto p-6">
                <div className="flex w-full flex-col-reverse items-center gap-6 lg:flex-row">
                    <div className="flex w-full flex-col gap-1">
                        <span className="text-secondary-foreground text-base">Hello, {"Marina"}</span>
                        <h2 className="text-2xl font-semibold">Account Overview</h2>
                    </div>

                    <div className="flex w-full flex-row gap-3">
                        <Button size={"lg"} variant={"default"} className={"ms-auto"}>
                            <ArrowUpRight /> Transfer
                        </Button>
                    </div>
                </div>

                <Card className="bg-gradient-primary">
                    <CardHeader>
                        <CardTitle className="text-secondary-foreground text-base">Liquid Balance</CardTitle>
                    </CardHeader>

                    <CardContent>
                        <div className="flex w-full flex-col gap-3">
                            <div className="flex flex-row gap-3">
                                <CardDescription className="text-4xl font-bold">USD {4000.0}</CardDescription>
                                <Badge variant={"secondary"}>
                                    <Plus className="size-3" />
                                    USD {125.0} this month
                                </Badge>
                            </div>

                            <span className="text-secondary-foreground text-base">
                                Follow your resources, attends and next payments in a single place.
                            </span>
                        </div>

                        <div className="flex w-max gap-3">
                            <div className="bg-secondary flex flex-col p-3">
                                <span className="bg-muted-foreground">Resources</span>
                                <span className="bg-primary-foreground">USD {1000.0}</span>
                            </div>

                            <div className="bg-secondary flex flex-col p-3">
                                <span className="bg-muted-foreground">Debts</span>
                                <span className="bg-primary-foreground">USD {5000.0}</span>
                            </div>
                        </div>
                    </CardContent>
                </Card>

                <div className="grid grid-cols-[66%_34%] gap-6">
                    <Card className="w-full">
                        <CardHeader>
                            <div className="flex w-full flex-col gap-4">
                                <CardTitle className="text-secondary-foreground text-base">Amount available</CardTitle>
                                <CardDescription className="text-3xl">USD {1000.0}</CardDescription>
                            </div>

                            <Button variant={"outline"}>
                                <Plus /> Add account
                            </Button>
                        </CardHeader>

                        <CardContent className="flex flex-row gap-3">
                            {accounts.map((account) => (
                                <div
                                    key={account.id}
                                    className="bg-accent flex w-[50%] flex-col gap-4 rounded-lg border"
                                >
                                    <div className="flex h-max w-full">
                                        <span className="bg-primary text-primary-foreground rounded-xl p-4">
                                            <Landmark className="size-10" />
                                        </span>

                                        <Badge variant={"secondary"} className="rounded-full shadow">
                                            {account.type}
                                        </Badge>
                                    </div>

                                    <span className="text-primary">{account.name}</span>

                                    <span className="text-primary text-2xl font-bold">USD {1000.0}</span>
                                </div>
                            ))}
                        </CardContent>
                    </Card>

                    <Card className="w-full">
                        <CardHeader>
                            <div className="flex w-full flex-col gap-4">
                                <CardDescription className="text-secondary-foreground">Next payment</CardDescription>
                                <CardTitle className="text-lg font-bold">Credit card</CardTitle>
                            </div>

                            <span className="bg-accent rounded-xl p-4">
                                <CreditCard className="text-primary size-10" />
                            </span>
                        </CardHeader>

                        <CardContent>
                            <div className="flex w-full flex-col gap-3">
                                <span className="text-3xl">USD {100.0}</span>

                                <span>Current invoice · Due in Jun 28</span>
                            </div>

                            <div className="flex flex-row justify-between gap-2">
                                <span className="text-sm">Used limit</span>
                                <span className="text-sm">10%</span>
                            </div>

                            <Progress value={10} max={100} className={"w-full"} />

                            <div className="flex flex-row justify-between gap-2">
                                <span className="text-base">Available</span>
                                <span className="text-success">USD {900.0}</span>
                            </div>

                            <Button variant={"secondary"} className={"w-full"}>
                                View card details
                            </Button>
                        </CardContent>
                    </Card>

                    <Card className="w-full">
                        <CardHeader>
                            <div className="flex w-full flex-col gap-4">
                                <CardTitle className="text-secondary-foreground text-base">Emprestimos </CardTitle>
                                <CardDescription className="text-lg font-semibold">Compromissos ativos</CardDescription>
                            </div>

                            <Button variant={"link"}>
                                View all <ArrowRight />
                            </Button>
                        </CardHeader>

                        <CardContent className="flex flex-row gap-3">
                            <div className="text-secondary flex w-full gap-4">
                                <span className="bg-accent rounded-xl p-4">
                                    <HandCoins className="text-primary size-10" />
                                </span>

                                <div className="flex w-full flex-col gap-4">
                                    <span className="text-foreground text-base font-semibold">Empréstimo pessoal </span>
                                    <span className="text-secondary-foreground">
                                        Taxa de juros 5% · sem vencimento próximo
                                    </span>
                                </div>
                                <div className="flex flex-col gap-4">
                                    <span className="text-secondary-foreground text-sm">Saldo devedor</span>
                                    <span className="text-foreground text-lg font-semibold">USD {5000.0}</span>
                                </div>
                            </div>
                        </CardContent>
                    </Card>

                    <Card className="w-full">
                        <CardHeader>
                            <span className="bg-success rounded-xl p-4">
                                <ShieldCheck className="text-primary-foreground size-10" />
                            </span>

                            <div className="flex w-full flex-col gap-4">
                                <CardTitle className="text-base font-bold">Your safety</CardTitle>
                                <CardDescription className="text-secondary-foreground">
                                    All is protected
                                </CardDescription>
                            </div>
                        </CardHeader>

                        <CardContent>
                            <p className="text-secondary-foreground">
                                Your access is secure and we dont identify incomuns activities.
                            </p>

                            <Button variant={"link"} className={"me-auto"}>
                                Review safety
                            </Button>
                        </CardContent>
                    </Card>
                </div>
            </main>
        </div>
    );
}
