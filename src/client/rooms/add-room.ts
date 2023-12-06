import FuseModule from "fuse.js"
import template from "./room-list.handlebars"
import "./add-room.scss"

const Fuse = FuseModule as unknown as typeof FuseModule.default; // Unfortunate hack, see https://github.com/krisk/Fuse/pull/727

type Room = {
    name: string
    ident: number
};
const fuse = new Fuse<Room>([], {
    keys: ["name"]
});

function loadRooms(server: string) {
    (<HTMLSelectElement>document.getElementById("server-select")!).disabled = true;
    (<HTMLInputElement>document.getElementById("search-rooms")!).disabled = true;
    (<HTMLInputElement>document.getElementById("submit")!).disabled = true;
    document.getElementById("room-list")?.replaceChildren();
    document.getElementById("room-no-results")!.classList.add("d-none");
    document.getElementById("room-spinner")!.classList.remove("d-none");
    fetch("/jankapi/ownedrooms", { method: "POST", body: JSON.stringify({ server: server }), headers: { "content-type": "application/json" } })
        .then((r) => r.json())
        .then((response) => {
            fuse.setCollection(response.rooms);
            for (let room of response.rooms) {
                document.getElementById("room-list")?.insertAdjacentHTML("beforeend", template({ ident: room.ident, name: room.name }));
            }
            if (Number.parseInt(document.body.dataset.userRole!) > 1) {
                document.getElementById("room-list")?.appendChild((<HTMLTemplateElement>document.getElementById("mod-room-entry")!).content.querySelector(".list-group-item")!.cloneNode(true));
            }
            if (response.rooms.length > 0) {
                (<HTMLInputElement>document.getElementById("submit")!).disabled = false;
            }
            else {
                document.getElementById("room-no-results")!.classList.remove("d-none");
            }
        })
        .finally(() => {
            (<HTMLSelectElement>document.getElementById("server-select")!).disabled = false;
            (<HTMLInputElement>document.getElementById("search-rooms")!).disabled = false;
            document.getElementById("room-spinner")!.classList.add("d-none");
        });
}

document.getElementById("search-rooms")!.addEventListener("input", (event) => {
    let query = (<HTMLInputElement>document.getElementById("search-rooms")!).value
    if (query.length == 0) {
        document.getElementById("room-no-results")!.classList.add("d-none")
        for (let element of document.getElementById("room-list")!.children) {
            element.classList.remove("d-none")
        }
    }
    else {
        let results = fuse.search(query)
        let idents = results.map((value) => value.item.ident)
        for (let element of document.getElementById("room-list")!.children) {
            if (idents.includes(Number.parseInt((<HTMLElement>element).dataset["roomIdent"]!))) {
                element.classList.remove("d-none")
            }
            else {
                element.classList.add("d-none")
            }
        }
        if (results.length == 0) {
            document.getElementById("room-no-results")!.classList.remove("d-none")
        }
        else {
            document.getElementById("room-no-results")!.classList.add("d-none")
        }
    }
})

document.querySelector("form")!.addEventListener("submit", () => {
    let elements = (<HTMLFormElement>document.querySelector("form")!).elements;
    if (elements["room-id"].value == "custom") {
        // this is an awful hack
        (<HTMLInputElement>document.getElementById("room-custom-id-radio")!).value = (<HTMLInputElement>document.getElementById("room-custom-id")!).value
    }
});

(<HTMLSelectElement>document.getElementById("server-select")!).addEventListener("change", function () { loadRooms(this.selectedOptions[0].value) })
loadRooms("https://chat.stackexchange.com")