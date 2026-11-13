// =====================================================================================
//  All The Stone 1  -  stone age progression
// -------------------------------------------------------------------------------------
//  1. The "pebble" mechanic: shift + right click with an EMPTY hand on stone or
//     cobblestone gives stone pebbles (50% chance). This is how a run starts, because a
//     solid stone world has no trees for a wooden pickaxe.
//
//  2. The bootstrap recipes that turn pebbles -> cobblestone -> gravel -> sand -> dirt ->
//     wood, so the Ex Deorum sieve chain can start without a single tree in the world.
//     Ex Deorum already provides pebble->cobblestone, cobblestone->gravel (hammer),
//     gravel->sand (hammer) and sand->dust (hammer); the recipes below fill the gaps:
//     dirt, saplings, sticks for the first tools and the first crafting table.
// =====================================================================================

const PEBBLE = "exdeorum:stone_pebble"
const PEBBLE_CHANCE = 0.5

// Blocks that give pebbles when punched with an empty hand.
const PEBBLE_SOURCES = [
    "minecraft:stone",
    "minecraft:cobblestone",
    "minecraft:smooth_stone",
    "minecraft:stone_bricks",
    "minecraft:granite",
    "minecraft:diorite",
    "minecraft:andesite",
    "minecraft:deepslate",
    "minecraft:cobbled_deepslate"
]

// -------------------------------------------------------------------------------------
//  1) shift + right click with an empty hand on stone  ->  50% pebble
// -------------------------------------------------------------------------------------
PEBBLE_SOURCES.forEach(blockId => {
    BlockEvents.rightClicked(blockId, event => {
        const player = event.player
        if (player == null) {
            return
        }

        // only with a bare hand, and only while sneaking, so normal right-click behaviour
        // of these blocks is never touched
        if (!player.mainHandItem.isEmpty() || !player.shiftKeyDown) {
            return
        }

        // stop the vanilla interaction and swing the arm as feedback
        event.cancel()
        player.swing()

        if (Math.random() < PEBBLE_CHANCE) {
            player.give(Item.of(PEBBLE))
            player.level.playSound(null, player.block.pos, "minecraft:block.stone.hit", "blocks", 0.7, 1.2)
        }
    })
})

// -------------------------------------------------------------------------------------
//  2) bootstrap recipes
// -------------------------------------------------------------------------------------
ServerEvents.recipes(event => {

    // ---- pebble -> cobblestone (Ex Deorum ships this; kept explicit so the pack can't
    //      break if that recipe is ever removed)
    event.shaped("minecraft:cobblestone", ["PP", "PP"], { P: PEBBLE })
        .id("allthestone1:cobblestone_from_pebbles")

    // ---- the first crafting table, without a single plank ------------------------------
    event.shaped("minecraft:crafting_table", ["CC", "PP"], {
        C: "minecraft:cobblestone",
        P: PEBBLE
    }).id("allthestone1:crafting_table_from_cobblestone")

    // ---- sticks from pebbles, so the first tools are reachable ------------------------
    event.shaped(Item.of("minecraft:stick", 4), ["P", "P"], { P: PEBBLE })
        .id("allthestone1:sticks_from_pebbles")

    // ---- a wooden hammer straight from pebbles + sticks (no log needed) ---------------
    event.shaped("exdeorum:wooden_hammer", ["PPP", " S ", " S "], {
        P: PEBBLE,
        S: "minecraft:stick"
    }).id("allthestone1:wooden_hammer_from_pebbles")

    // ---- dirt: 4 gravel + 4 sand / dust (the brief's recipe) --------------------------
    event.shaped("minecraft:dirt", ["GS", "SG"], {
        G: "minecraft:gravel",
        S: Ingredient.of(["minecraft:sand", "exdeorum:dust"])
    }).id("allthestone1:dirt_from_gravel_and_sand")

    // ---- bone meal out of stone dust (no bones in a stone world for a long time) ------
    event.shapeless(Item.of("minecraft:bone_meal", 1), ["exdeorum:dust", "exdeorum:dust", "exdeorum:dust"])
        .id("allthestone1:bone_meal_from_dust")

    // ---- one oak sapling from dirt + bone meal / dust + a pebble ----------------------
    event.shaped("minecraft:oak_sapling", [" B ", "BDB", " P "], {
        B: Ingredient.of(["minecraft:bone_meal", "exdeorum:dust"]),
        D: "minecraft:dirt",
        P: PEBBLE
    }).id("allthestone1:oak_sapling_from_dirt_and_bone_meal")

    // ---- string for the first sieve mesh, out of hammered wood ------------------------
    event.shapeless(Item.of("minecraft:string", 2), ["exdeorum:wood_chippings", "exdeorum:wood_chippings"])
        .id("allthestone1:string_from_wood_chippings")

    // ---- flint for the flint mesh, out of gravel --------------------------------------
    event.shapeless(Item.of("minecraft:flint", 1),
        ["minecraft:gravel", "minecraft:gravel", "minecraft:gravel", "minecraft:gravel"])
        .id("allthestone1:flint_from_gravel")

    // ---- andesite / diorite / granite so every sieve drop has a use -------------------
    event.shapeless("minecraft:andesite", ["minecraft:cobblestone", "exdeorum:dust"])
        .id("allthestone1:andesite_from_cobblestone")
    event.shapeless("minecraft:diorite", ["minecraft:cobblestone", "minecraft:bone_meal"])
        .id("allthestone1:diorite_from_cobblestone")
    event.shapeless("minecraft:granite", ["minecraft:cobblestone", "minecraft:flint"])
        .id("allthestone1:granite_from_cobblestone")

    // ---- charcoal-less torches: stick + dust (coal comes later, from the sieve) -------
    event.shaped(Item.of("minecraft:torch", 4), ["D", "S"], {
        D: Ingredient.of(["exdeorum:dust", "minecraft:coal"]),
        S: "minecraft:stick"
    }).id("allthestone1:torch_from_dust")
})

// -------------------------------------------------------------------------------------
//  3) Small quality-of-life touches
// -------------------------------------------------------------------------------------
// A brand new player gets the quest book and the hammer from stone_block_spawn.js.
// Nothing else is needed here.
