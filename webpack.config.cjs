const path = require("path")
const MiniCssExtractPlugin = require("mini-css-extract-plugin");
const CssMinimizerPlugin = require("css-minimizer-webpack-plugin");

module.exports = {
    mode: "development",
    devtool: 'inline-source-map',
    entry: {
        common: "./src/client/common/common.ts",
        login: "./src/client/login/login.ts",
        error: "./src/client/error/error.ts",
        rooms: "./src/client/rooms/rooms.ts",
        addroom: "./src/client/rooms/add-room.ts"
    },
    module: {
        rules: [
            {
                test: /\.tsx?$/,
                use: 'ts-loader',
                exclude: /node_modules/,
            },
            {
                test: /\.s[ac]ss$/i,
                use: [
                    MiniCssExtractPlugin.loader,
                    "css-loader",
                    "sass-loader",
                ],
            },
            {
                test: /\.handlebars$/,
                loader: "handlebars-loader"
            }
        ],
    },
    resolve: {
        extensions: ['.tsx', '.ts', '.js'],
    },
    output: {
        filename: "[name].bundle.js",
        path: path.resolve(__dirname) + "/static"
    },
    plugins: [new MiniCssExtractPlugin()],
    optimization: {
        minimizer: [
            `...`,
            new CssMinimizerPlugin()
        ],
    },
    ignoreWarnings: [
        /Passing percentage units to the global abs\(\) function/ // shut up bootstrap
    ]
}