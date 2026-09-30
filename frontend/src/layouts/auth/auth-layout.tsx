import { ToggleGroup, ToggleGroupItem } from "@/components/ui/toggle-group";
import { Avatar, AvatarFallback, AvatarImage } from "@/components/ui/avatar";
import { Card, CardContent, CardHeader } from "@/components/ui/card";
import useSystem from "@/contexts/system/use-system";
import { AuthLayoutProps } from "./types";

export default function AuthLayout(props: AuthLayoutProps) {
    const { language, setLanguage } = useSystem();

    return (
        <div className="bg-gradient-primary flex h-svh w-svw justify-center gap-3 overflow-x-hidden overflow-y-auto px-3 py-3">
            <div className="flex w-full flex-col gap-3 pb-3! md:w-md">
                <div className="flex w-full">
                    <ToggleGroup
                        multiple={false}
                        className={"ms-auto"}
                        onValueChange={(language) => setLanguage(language[0])}
                        value={[language]}
                    >
                        <ToggleGroupItem value={"es"}>ES</ToggleGroupItem>
                        <ToggleGroupItem value={"pt"}>PT</ToggleGroupItem>
                    </ToggleGroup>
                </div>

                <Card className="min-h-max">
                    <CardHeader className="flex flex-row gap-2">
                        <Avatar className={"size-12"}>
                            <AvatarImage className={"rounded-sm"} src="/favicon.svg" alt="Avatar" />
                            <AvatarFallback>BL</AvatarFallback>
                        </Avatar>

                        <div className="flex h-full flex-col gap-1">
                            <h1 className="text-xl">Banco LATAM</h1>
                            <span className="text-muted-foreground text-xs">México · Colombia · Argentina</span>
                        </div>
                    </CardHeader>

                    <CardContent>{props.children}</CardContent>
                </Card>
            </div>
        </div>
    );
}
